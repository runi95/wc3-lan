# wc3-lan's LAN switch for Windows (untested on Windows; read it before you run it).
#
#   1. finds Warcraft III and, in its executable memory, the routine that sets up local play:
#        48 83 EC 58  E8 ?? ?? ?? ??  B9 50 4F 4F 4C  E8 ...
#        sub rsp,58   call ...        mov ecx,'LOOP'   call SelectNetProvider   <- breakpoint here
#   2. attaches as a debugger and puts a hardware breakpoint (CPU register Dr0) on that last call;
#      no game code is changed
#   3. when you click Local Area Network, the game stops there: RCX holds 'LOOP' (4C4F4F50) and is
#      changed to 'TCPN' (5443504E), the LAN mode
#   4. clears the breakpoint and detaches; the game carries on without a debugger
# If nothing happens within 2 minutes, or anything fails, it clears the breakpoint and detaches.
#
# This needs a menu page (turns the Local Area Network button on). Run it with the game
# on the main menu, from a 64-bit PowerShell:
#   powershell -ExecutionPolicy Bypass -File lan-switch.ps1
#   powershell -ExecutionPolicy Bypass -File lan-switch.ps1 -Address 0x7FF6... (skip the search)
param(
    [string]$Address = "",
    [int]$TimeoutSeconds = 120
)
$ErrorActionPreference = "Stop"
if (-not [Environment]::Is64BitProcess) { throw "Run this from 64-bit PowerShell (the game is 64-bit)." }

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class Wc3LanSwitch
{
    // --- Windows functions used (all from kernel32.dll) ---------------------------------------
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr VirtualQueryEx(IntPtr process, IntPtr address, out MemoryInfo info, IntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] buffer, IntPtr size, out IntPtr read);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool DebugActiveProcess(int pid);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool DebugActiveProcessStop(int pid);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool DebugSetProcessKillOnExit(bool kill);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool WaitForDebugEvent(IntPtr debugEvent, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool ContinueDebugEvent(int pid, int tid, uint status);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool GetThreadContext(IntPtr thread, IntPtr context);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetThreadContext(IntPtr thread, IntPtr context);
    [DllImport("kernel32.dll", SetLastError = true)] static extern uint SuspendThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] static extern uint ResumeThread(IntPtr thread);

    // MEMORY_BASIC_INFORMATION (64-bit)
    [StructLayout(LayoutKind.Sequential)]
    public struct MemoryInfo
    {
        public IntPtr BaseAddress, AllocationBase;
        public uint AllocationProtect, PartitionId;
        public IntPtr RegionSize;
        public uint State, Protect, Type, Padding;
    }

    const uint PROCESS_QUERY_INFORMATION = 0x0400, PROCESS_VM_READ = 0x0010;
    const uint MEM_COMMIT = 0x1000, PAGE_GUARD = 0x100;
    const uint EXECUTABLE = 0x10 | 0x20 | 0x40 | 0x80;   // PAGE_EXECUTE, _READ, _READWRITE, _WRITECOPY

    public const long LOOP = 0x4C4F4F50, TCPN = 0x5443504E;
    // The pattern; -1 = any byte (the call's relative address)
    static readonly int[] Pattern = { 0x48, 0x83, 0xEC, 0x58, 0xE8, -1, -1, -1, -1, 0xB9, 0x50, 0x4F, 0x4F, 0x4C, 0xE8 };
    public const int CallOffset = 14;   // the "call SelectNetProvider" after mov ecx,'LOOP'

    // --- 1. Find the routine: read-only search of executable memory ---------------------------
    public static List<long> Find(int pid)
    {
        var found = new List<long>();
        IntPtr process = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, false, pid);
        if (process == IntPtr.Zero) throw new Exception("can't open the game (error " + Marshal.GetLastWin32Error() + ")");
        try
        {
            long address = 0;
            MemoryInfo info;
            while (VirtualQueryEx(process, new IntPtr(address), out info, new IntPtr(Marshal.SizeOf(typeof(MemoryInfo)))) != IntPtr.Zero)
            {
                long start = info.BaseAddress.ToInt64(), size = info.RegionSize.ToInt64();
                if (info.State == MEM_COMMIT && (info.Protect & EXECUTABLE) != 0 && (info.Protect & PAGE_GUARD) == 0)
                    Search(process, start, size, found);
                address = start + size;
                if (size <= 0) break;
            }
        }
        finally { CloseHandle(process); }
        return found;
    }

    static void Search(IntPtr process, long start, long size, List<long> found)
    {
        const long chunk = 16 << 20;
        for (long offset = 0; offset < size; offset += chunk - Pattern.Length)
        {
            long length = Math.Min(chunk, size - offset);
            var buffer = new byte[length];
            IntPtr read;
            if (!ReadProcessMemory(process, new IntPtr(start + offset), buffer, new IntPtr(length), out read)) continue;
            for (long i = 0; i + Pattern.Length <= read.ToInt64(); i++)
            {
                int j = 0;
                while (j < Pattern.Length && (Pattern[j] < 0 || buffer[i + j] == Pattern[j])) j++;
                if (j == Pattern.Length && !found.Contains(start + offset + i)) found.Add(start + offset + i);
            }
            if (length < chunk) break;
        }
    }

    // --- Thread registers (x64 CONTEXT: 16-byte aligned, 0x4D0 bytes) --------------------------
    const int CONTEXT_SIZE = 0x4D0;
    const int OFF_FLAGS = 0x30, OFF_DR0 = 0x48, OFF_DR7 = 0x70, OFF_RCX = 0x80;
    const uint CONTEXT_INTEGER = 0x00100002, CONTEXT_DEBUG_REGISTERS = 0x00100010;
    static IntPtr raw = Marshal.AllocHGlobal(CONTEXT_SIZE + 16);
    static IntPtr context = new IntPtr((raw.ToInt64() + 15) & ~15L);

    static bool Load(IntPtr thread, uint flags)
    {
        Marshal.Copy(new byte[CONTEXT_SIZE], 0, context, CONTEXT_SIZE);
        Marshal.WriteInt32(context, OFF_FLAGS, (int)flags);
        return GetThreadContext(thread, context);
    }

    static bool Store(IntPtr thread, uint flags)
    {
        Marshal.WriteInt32(context, OFF_FLAGS, (int)flags);
        return SetThreadContext(thread, context);
    }

    // Dr0 = breakpoint address, Dr7 bit 0 = enabled, as an execute breakpoint; (0, 0) clears it
    static bool Breakpoint(IntPtr thread, long address, long dr7)
    {
        if (!Load(thread, CONTEXT_DEBUG_REGISTERS)) return false;
        Marshal.WriteInt64(context, OFF_DR0, address);
        Marshal.WriteInt64(context, OFF_DR7, dr7);
        return Store(thread, CONTEXT_DEBUG_REGISTERS);
    }

    // --- 2-4. Attach, wait for the click, switch, detach ----------------------------------------
    const int EXCEPTION_EVENT = 1, CREATE_THREAD = 2, CREATE_PROCESS = 3, EXIT_THREAD = 4, EXIT_PROCESS = 5, LOAD_DLL = 6;
    const uint DBG_CONTINUE = 0x00010002, DBG_EXCEPTION_NOT_HANDLED = 0x80010001;
    const uint EXCEPTION_BREAKPOINT = 0x80000003, EXCEPTION_SINGLE_STEP = 0x80000004;

    public static string Switch(int pid, long site, int timeoutSeconds)
    {
        long call = site + CallOffset;
        var threads = new Dictionary<int, IntPtr>();
        IntPtr debugEvent = Marshal.AllocHGlobal(256);   // DEBUG_EVENT (176 bytes on x64)
        bool armed = false, done = false;
        string result = "timed out after " + timeoutSeconds + " s: Local Area Network wasn't clicked";
        DateTime deadline = DateTime.Now.AddSeconds(timeoutSeconds);

        if (!DebugActiveProcess(pid)) return "couldn't attach (error " + Marshal.GetLastWin32Error() + ")";
        DebugSetProcessKillOnExit(false);   // ending this script must never end the game
        try
        {
            while (!done && DateTime.Now < deadline)
            {
                if (!WaitForDebugEvent(debugEvent, 500)) continue;
                int code = Marshal.ReadInt32(debugEvent, 0), tid = Marshal.ReadInt32(debugEvent, 8);
                uint status = DBG_CONTINUE;
                switch (code)
                {
                    case CREATE_PROCESS:   // hFile at 16, hThread at 32
                        CloseHandle(Marshal.ReadIntPtr(debugEvent, 16));
                        threads[tid] = Marshal.ReadIntPtr(debugEvent, 32);
                        break;
                    case CREATE_THREAD:    // hThread at 16; a thread started after arming gets the breakpoint too
                        threads[tid] = Marshal.ReadIntPtr(debugEvent, 16);
                        if (armed) Breakpoint(threads[tid], call, 1);
                        break;
                    case EXIT_THREAD:
                        threads.Remove(tid);
                        break;
                    case EXIT_PROCESS:
                        return "the game exited";
                    case LOAD_DLL:         // hFile at 16
                        CloseHandle(Marshal.ReadIntPtr(debugEvent, 16));
                        break;
                    case EXCEPTION_EVENT:  // ExceptionCode at 16, ExceptionAddress at 32
                    {
                        uint exception = (uint)Marshal.ReadInt32(debugEvent, 16);
                        long at = Marshal.ReadIntPtr(debugEvent, 32).ToInt64();
                        if (exception == EXCEPTION_BREAKPOINT && !armed)
                        {
                            // Windows' own breakpoint after attaching: every thread is stopped now
                            foreach (var thread in threads.Values) Breakpoint(thread, call, 1);
                            armed = true;
                            Console.WriteLine("Ready. Click Local Area Network in the game now.");
                        }
                        else if (exception == EXCEPTION_SINGLE_STEP && at == call && threads.ContainsKey(tid))
                        {
                            IntPtr thread = threads[tid];
                            if (Load(thread, CONTEXT_INTEGER))
                            {
                                long rcx = Marshal.ReadInt64(context, OFF_RCX);
                                if (rcx == LOOP)
                                {
                                    Marshal.WriteInt64(context, OFF_RCX, TCPN);
                                    result = Store(thread, CONTEXT_INTEGER)
                                        ? "switched: RCX was 4C4F4F50 (LOOP), is now 5443504E (TCPN)"
                                        : "couldn't change RCX (error " + Marshal.GetLastWin32Error() + ")";
                                }
                                else result = "RCX was " + rcx.ToString("X") + ", not LOOP; left it alone";
                            }
                            foreach (var t in threads.Values) Breakpoint(t, 0, 0);
                            done = true;
                        }
                        else status = DBG_EXCEPTION_NOT_HANDLED;   // the game's own; let it handle them
                        break;
                    }
                }
                ContinueDebugEvent(Marshal.ReadInt32(debugEvent, 4), tid, status);
            }
        }
        finally
        {
            if (armed && !done)
            {
                // Timed out or failed with the breakpoint still set: threads are running, so pause
                // each one to clear it; a leftover breakpoint would crash the game after detaching
                foreach (var thread in threads.Values)
                {
                    SuspendThread(thread);
                    Breakpoint(thread, 0, 0);
                    ResumeThread(thread);
                }
            }
            DebugActiveProcessStop(pid);
            Marshal.FreeHGlobal(debugEvent);
        }
        return result;
    }
}
'@

$game = @(Get-Process -Name "Warcraft III" -ErrorAction SilentlyContinue)
if ($game.Count -ne 1) { throw "Start Warcraft III first (found $($game.Count) running)." }
$game = $game[0]
$version = (Get-Item $game.Path).VersionInfo.FileVersion
Write-Host "Warcraft III is running (process $($game.Id), version $version)."
if ($version -notmatch "24268") {
    throw "The debugger switch supports only build 24268. Build 24371 uses windows\loop-lan.ps1; see docs\windows-24371.md. No debugger was attached."
}

if ($Address) {
    $site = [Convert]::ToInt64(($Address -replace "^0x", ""), 16)
} else {
    Write-Host "Searching the game's executable memory for the local-play routine (read-only)..."
    $found = [Wc3LanSwitch]::Find($game.Id)
    if ($found.Count -ne 1) {
        $list = ($found | ForEach-Object { "0x{0:X}" -f $_ }) -join ", "
        throw "Expected the pattern once, found it $($found.Count) times ($list). Check them in a debugger such as x64dbg and pass one with -Address."
    }
    $site = $found[0]
}
Write-Host ("Routine at 0x{0:X}; the breakpoint goes on its call at 0x{1:X}." -f $site, ($site + [Wc3LanSwitch]::CallOffset))

$answer = Read-Host "Attach to the game as a debugger now? (y/n)"
if ($answer -ne "y") { Write-Host "Nothing done."; return }
Write-Host "Attaching. The game freezes for a moment."
$result = [Wc3LanSwitch]::Switch($game.Id, $site, $TimeoutSeconds)
Write-Host "Done: $result. The debugger has detached."
