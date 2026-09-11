"""Publish a small, dated repair audit next to the data manifest, not to main."""
import base64
import json
from data_sync import utc_now


def publish_report(writer, manifest, before, after, collection):
    writer._ensure_data_branch()
    path='dashboard/quality-repair-latest.json'
    old=writer._json('GET','/contents/'+path,missing=True,params={'ref':writer.branch})
    report={'generated_at':utc_now(),'app_version':manifest['app_version'],'generation':manifest['generation'],
            'before':before['counts'],'after':after['counts'],'quote_missing':after['quote_missing'],
            'information_missing':after['information_missing'],'ranking_universe_difference':after['ranking_universe_only'],
            'bad_history':after['bad_history'],'examples':after['samples'],'collection':collection}
    raw=json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2).encode()
    body={'message':'Record data completeness repair audit','branch':writer.branch,'content':base64.b64encode(raw).decode()}
    if old:body['sha']=old['sha']
    writer._json('PUT','/contents/'+path,json=body)
    return report
