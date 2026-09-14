"""A retained receipt cannot authorize interactions during a new app rerun."""
import ast
import json
from pathlib import Path
import shutil
import subprocess

import pytest

def test_real_readiness_predicate_requires_idle_connection_and_current_receipt():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the actual browser predicate')

    class App:
        def wait_for_function(self, expression, *, arg, timeout):
            self.expression=expression
            self.arg=arg
        def locator(self, _):
            return self
        def count(self):
            return 0

    # The normal unit-test environment does not install Playwright. Execute the
    # actual helper body without importing its unrelated browser-launch module.
    tree=ast.parse(Path(__file__).parents[1].joinpath('production_smoke.py').read_text())
    helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='wait_page_ready')
    scope={'no_exception':lambda _:None}
    exec(compile(ast.Module(body=[helper],type_ignores=[]),'production_smoke.py','exec'),scope)
    app=App()
    scope['wait_page_ready'](app,'AAPL','AAPL')
    harness=r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
const predicate=JSON.parse(process.argv[1]), args=JSON.parse(process.argv[2]);
function ready(change={}) {
  const state={script:'notRunning',connection:'CONNECTED',ticker:'AAPL',search:'AAPL',
    stale:false,receipt:true,root:true,...change};
  const root={getAttribute(name){return name==='data-test-script-state' ? state.script : state.connection;}};
  const receipt={dataset:{ticker:state.ticker,search:state.search},closest(){return state.stale ? {} : null;}};
  const document={querySelector(){return state.root ? root : null;},
    querySelectorAll(){return state.receipt ? [receipt] : [];}};
  return Boolean(vm.runInNewContext('('+predicate+')(args)',{document,args}));
}
assert.equal(ready(),true,'completed connected matching page is usable');
assert.equal(ready({script:'running'}),false,'old matching receipt during full rerun is not ready');
assert.equal(ready({connection:'DISCONNECTED'}),false,'disconnected old page is not ready');
assert.equal(ready({root:false}),false,'absent app is not ready');
assert.equal(ready({receipt:false}),false,'idle without a completed page is not ready');
assert.equal(ready({stale:true}),false,'stale completed receipt is not current');
assert.equal(ready({ticker:'MSFT'}),false,'wrong stock is not ready');
assert.equal(ready({search:'MSFT'}),false,'old query is not ready');
'''
    result=subprocess.run([node,'-e',harness,json.dumps(app.expression),json.dumps(app.arg)],
                          capture_output=True,text=True)
    assert result.returncode==0,result.stderr
