// Exercise the adapter-missing behavior that previously silently selected LOOP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const page = fs.readFileSync(require('node:path').join(__dirname,'../page/windows-loop.html'),'utf8');
class NativeSocket {
    constructor() { this.sent=[];this.listeners=[]; }
    send(text) { this.sent.push(JSON.parse(text)); }
    addEventListener(type,fn) { if(type==='message')this.listeners.push(fn); }
    deliver(message) { for(const fn of this.listeners)fn({data:JSON.stringify(message)}); }
}
const elements=[];
const document={getElementById:id=>elements.find(x=>x.id===id),
    createElement:tag=>({tag,style:{},setAttribute(){},appendChild(child){this.child=child;}}),
    body:{appendChild:element=>elements.push(element)}};
const window={WebSocket:NativeSocket};
vm.runInNewContext(page.match(/<script>([\s\S]*?)<\/script>/)[1],{
    window,document,MessageEvent:class {constructor(type,options){this.data=options.data;}}
});
const socket=new window.WebSocket('ws://127.0.0.1:1234/webui-socket/123');
const send=(message,payload={})=>socket.send(JSON.stringify({type:'webui',message,payload}));
send('InitializeNetProvider',{id:'CSDK'});
assert.equal(socket.sent.length,0);
assert.equal(elements.length,1);
assert.ok(elements[0].textContent.includes('loop-lan.ps1'));
elements[0].child.onclick();assert.equal(elements[0].style.display,'none');
send('CreateLobby');send('JoinGame');
assert.equal(socket.sent.length,0);
assert.equal(elements.length,1);assert.equal(elements[0].style.display,'block');
let received;
socket.addEventListener('message',e=>received=JSON.parse(e.data));
socket.deliver({messageType:'FeatureFlags',payload:{data:{enableLanMode:false}}});
assert.equal(received.payload.data.enableLanMode,true);
socket.deliver({messageType:'SetGlueScreen',payload:{screen:'MAIN_MENU'}});
send('InitializeLocalNetProvider');send('CreateLobby');
assert.deepEqual(socket.sent.map(x=>x.message),['InitializeLocalNetProvider','CreateLobby']);
console.log('Windows page: missing-adapter gate, LAN actions, flags and single-player reset passed.');
