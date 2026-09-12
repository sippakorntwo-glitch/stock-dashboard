"""Regression for the cold-start frontend delta-path failure seen in browser CI."""
import ast
from pathlib import Path


def test_footer_is_reserved_before_dynamic_content_and_cache_spinners():
    tree=ast.parse(Path('dashboard_ui.py').read_text())
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    reserved={}
    for position,node in enumerate(main.body):
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call):
            call=node.value
            if isinstance(call.func,ast.Attribute) and call.func.attr=='container':
                for kw in call.keywords:
                    if kw.arg=='key' and isinstance(kw.value,ast.Constant):
                        reserved[kw.value.value]=(position,node.targets[0].id)
    assert set(reserved)=={'workspace_body','workspace_footer'}
    body=next(n for n in main.body if isinstance(n,ast.With) and isinstance(n.items[0].context_expr,ast.Name) and n.items[0].context_expr.id=='body')
    footer=next(n for n in main.body if isinstance(n,ast.With) and isinstance(n.items[0].context_expr,ast.Name) and n.items[0].context_expr.id=='footer')
    assert reserved['workspace_body'][0]<reserved['workspace_footer'][0]<main.body.index(body)<main.body.index(footer)
    body_names={n.func.id for n in ast.walk(body) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    footer_names={n.func.id for n in ast.walk(footer) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
    assert 'industry_summary' in body_names and '_poll_data' not in body_names
    assert '_poll_data' in footer_names and 'page_receipt' in footer_names
    assert not any(isinstance(n,ast.If) for n in footer.body)
