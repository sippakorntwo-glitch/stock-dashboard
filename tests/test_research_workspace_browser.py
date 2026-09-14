"""Execute the actual dependency-free browser bridge against isolated storage."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def test_actual_javascript_storage_hydration_roundtrip_and_isolation():
    node = shutil.which('node')
    if not node: pytest.skip('Node is needed for the browser protocol unit harness')
    source = Path(__file__).parents[1].joinpath('research_workspace_component/index.html').read_text()
    javascript = re.search(r'<script>([\s\S]+)</script>', source).group(1)
    harness = r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
const script=JSON.parse(process.argv[1]);
function browser(initial, blocked=false){
  const elements={}, listeners={}, messages=[], storage=new Map(Object.entries(initial||{}));let writes=0;
  const element=id=>elements[id]||(elements[id]={value:'',disabled:true,textContent:'',children:[],handlers:{},
    addEventListener(type,fn){this.handlers[type]=fn;},replaceChildren(){this.children=[];this.value='';},
    append(option){this.children.push(option);if(this.children.length===1)this.value=option.value;}});
  const parent={postMessage(message){messages.push(message);}};
  const window={parent,confirm:()=>true,addEventListener(type,fn){listeners[type]=fn;},
    localStorage:{getItem(key){if(blocked)throw Error('blocked');return storage.get(key)||null;},
      setItem(key,value){if(blocked)throw Error('blocked');writes++;storage.set(key,value);}}};
  const document={body:{scrollHeight:250},getElementById:element,
    createElement:()=>({value:'',textContent:''}),documentElement:{style:{setProperty(){}}}};
  const context={window,document,TextEncoder,structuredClone,Date,Math,JSON};
  vm.runInNewContext(script,context);
  return {elements,messages,storage,get writes(){return writes;},
    render(args,source=parent){listeners.message({source,data:{type:'streamlit:render',args}});},
    click(id){element(id).handlers.click();}};
}
const key='stock-research-workspace:private:v1';
const oldResearch={notes:{MSFT:'private note'},tracking:{},baselines:{}};
const saved={schema:1,name:'growth',saved_at:'2026-09-14',preferences:{selected_ticker:'MSFT',screen_min_ROE:15},research:oldResearch};
const a=browser({[key]:JSON.stringify({schema:1,workspaces:[saved],draft:oldResearch})});
const empty={notes:{},tracking:{},baselines:{}};
const args={document:saved,draft:empty,draft_revision:'empty',hydrated:false};
a.render(args,{});assert.equal(a.elements['save'].disabled,true,'ignore foreign messages');
a.render(args);assert.equal(a.writes,0,'initial render must not erase persisted notes');
const hydrate=a.messages.find(m=>m.value?.action==='hydrate');assert.equal(hydrate.value.research.notes.MSFT,'private note');
a.render({...args,hydrated:true,draft:oldResearch,draft_revision:'restored'});
assert.equal(a.writes,1);a.render({...args,hydrated:true,draft:oldResearch,draft_revision:'restored'});
assert.equal(a.writes,1,'unchanged refresh is coalesced');
a.elements['workspace-name'].value='new view';a.click('save');
assert.equal(JSON.parse(a.storage.get(key)).workspaces.length,2);
a.click('load');assert.equal(a.messages.at(-1).value.document.name,'new view');
assert.equal(a.messages.at(-1).value.document.preferences.selected_ticker,'MSFT');
const b=browser();b.render(args);const bh=b.messages.find(m=>m.value?.action==='hydrate');
assert.equal(Object.keys(bh.value.research).length,0,'a separate browser cannot see private data');
const reopened=browser(Object.fromEntries(a.storage));reopened.render(args);
assert.equal(reopened.elements['workspace-list'].children.length,2,'named views survive reopening');
const denied=browser({},true);denied.render(args);
assert.match(denied.elements.status.textContent,/JSON/,'blocked storage has file fallback');
denied.render({...args,hydrated:true});assert.equal(denied.writes,0);
const corrupt=browser({[key]:'bad json'});corrupt.render(args);
assert.match(corrupt.elements.status.textContent,/JSON/);assert.equal(corrupt.writes,0);
const before=a.messages.filter(m=>m.value?.action==='hydrate').length;
a.render({...args,boot_token:'reconnected'});
assert.equal(a.messages.filter(m=>m.value?.action==='hydrate').length,before+1,'rehydrate surviving iframe for new server session');
a.render({...args,boot_token:'reconnected'});
assert.equal(a.messages.filter(m=>m.value?.action==='hydrate').length,before+1,'one hydration per session token');
'''
    result = subprocess.run([node, '-e', harness, json.dumps(javascript)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
