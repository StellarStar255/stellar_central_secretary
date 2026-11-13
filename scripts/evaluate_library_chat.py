"""Opt-in live-model evaluation using synthetic material, never the user's library."""
import argparse,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--run-model',action='store_true',help='Send synthetic fixtures through the selected signed-in CLI')
 parser.add_argument('--backend',choices=('codex','claude','gemini'),default='codex')
 parser.add_argument('--case',action='append',help='Fixture name; omit to run all cases')
 parser.add_argument('--output',type=Path,default=Path('/tmp/stellar-chat-evaluation.json'))
 args=parser.parse_args()
 if not args.run_model:parser.error('Use --run-model to authorize actual model calls for synthetic fixtures.')
 cases=json.loads((Path(__file__).resolve().parent.parent/'tests/fixtures/conversation_regressions.json').read_text())
 if args.case:
  unknown=set(args.case)-{case['name'] for case in cases}
  if unknown:parser.error('Unknown fixture: '+', '.join(sorted(unknown)))
  cases=[case for case in cases if case['name'] in args.case]
 report=[]
 with tempfile.TemporaryDirectory(prefix='stellar-chat-evaluation-') as root:
  service=Service(root);service.archive.configure(args.backend,False)
  try:
   course=service.archive.add('课程表','示例课表适用11月2日至8日，第9周。周一09:45至11:55有材料课；周二下午13:00至16:10空白；周四14:00有材料课。16:15以后未显示。')[0]
   rome=service.archive.add('罗马皇位继承','罗马皇位继承受军队拥立、政治承认和养子制度影响，并非稳定的嫡长子继承。')[0]
   daughter=service.archive.add('女儿课表','女儿周二上午09:00有音乐课。')[0]
   turns=[{'question':'我老婆今天下午有课吗？','answer':'课表周四14:00有课。[1]','source_ids':[course]}]
   context=[{'statement':'这张课程表就是她的，本周也按这张表判断。','source_ids':[course]}]
   with patch('secretary.knowledge_chat.current_time',return_value={'date':'2026-11-12','weekday':'星期四','time':'12:00','timezone':'CST','utc_offset':'+0800'}):
    for case in cases:
     print('Evaluating '+case['name'],flush=True)
     try:
      result=service.ask_library(case['question'],[] if case['name']=='schedule_today' else turns,context=[] if case['name']=='schedule_today' else context,force_refresh=True)
      expected={'course':course,'rome':rome,'daughter':daughter}[case['topic']]
      report.append({'case':case['name'],'question':case['question'],'answer':result['answer'],'timings':result.get('timings',{}),'expected_topic_cited':any(s['item_id']==expected for s in result['sources']),'sources':[s['title'] for s in result['sources']],'catalog_queries':result.get('catalog',{}).get('queries',[]),'review_required':True})
     except Exception as error:report.append({'case':case['name'],'error':str(error),'review_required':True})
  finally:service.close()
 args.output.write_text(json.dumps({'backend':args.backend,'synthetic_only':True,'cases':report},ensure_ascii=False,indent=2)+'\n')
 print('Saved evaluation report: '+str(args.output))
 return 1 if any('error' in case for case in report) else 0
if __name__=='__main__':raise SystemExit(main())
