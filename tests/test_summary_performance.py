import base64,json,tempfile,threading,time,unittest
from unittest.mock import patch
from secretary import ai
from secretary.server import Service
from secretary.summary_jobs import SummaryJobs

def wait(check):
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        if check():return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for synthetic model work')

class SummaryPerformanceTest(unittest.TestCase):
    def test_short_prompts_are_bounded_and_long_text_keeps_hierarchical_coverage(self):
        value={'title':'Synthetic','summary':'Summary','category':'Test','tags':[]}
        with patch.object(ai,'run',return_value=json.dumps(value)) as model:
            ai.summarize('tar -czf samples.tar.gz samples/','Commands','codex')
            self.assertIn('最多120字',model.call_args.args[0]);self.assertEqual(model.call_count,1)
            model.reset_mock();ai.summarize('x'*25000,'Long source','codex')
            self.assertEqual(model.call_count,3)
        self.assertIn('100到200',ai.summary_instruction('x'*2000))
        self.assertIn('200到500',ai.summary_instruction('image description',images=True))

    def test_short_job_runs_while_both_long_executor_workers_are_occupied(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);release=threading.Event();long_started=threading.Event();short_done=threading.Event()
            active=[0,0];guard=threading.Lock()
            def summarize(item,*args,**kwargs):
                with guard:active[0]+=1;active[1]=max(active)
                try:
                    if len(item['text'])>4000:
                        long_started.set();self.assertTrue(release.wait(4))
                    else:short_done.set()
                    ai.report('waiting_model')
                    return {'summary':'Synthetic summary','state':'ready','error':''}
                finally:
                    with guard:active[0]-=1
            try:
                with patch.object(ai,'summary_fields',side_effect=summarize):
                    first,_=service.archive.add('Long first','a'*5000);second,_=service.archive.add('Long second','b'*5000);short,_=service.archive.add('Short','tar -czf samples.tar.gz samples/')
                    service.queue(first,force=True);self.assertTrue(long_started.wait(2));service.queue(second,force=True);service.queue(short,force=True)
                    self.assertTrue(short_done.wait(2),'A long archive must not block the short lane')
                    wait(lambda:service.archive.get(short)['state']=='ready')
                    self.assertLessEqual(active[1],2)
                    progress=service.item_detail(short)['summary_progress'];self.assertEqual(progress['stage'],'done');self.assertFalse(progress['active']);self.assertEqual(progress['lane'],'short')
                    self.assertEqual(service.summary_jobs.snapshot(second)['stage'],'queued')
                    release.set();wait(lambda:not service.runtime()['processing'])
                    self.assertEqual(service.archive.get(second)['state'],'ready')
            finally:release.set();service.close()

    def test_archive_only_never_invokes_models_fetches_or_browser_and_stays_saved(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',True)
            try:
                with patch.object(service,'queue') as queue,patch.object(service,'start_capture') as capture,patch('secretary.server.fetch_page') as fetch,patch.object(service,'read_group_links') as group:
                    note=service.ingest({'text':'tar -czf samples.tar.gz samples/','archive_only':True})['item']
                    file=service.ingest({'filename':'commands.txt','data':base64.b64encode(b'echo synthetic').decode(),'archive_only':True})['item']
                    link=service.ingest({'url':'https://example.invalid/private','archive_only':True})['item']
                    bundle=service.ingest({'text':'Related synthetic sources','attachments':[],'links':['https://example.invalid/a','https://example.invalid/b'],'archive_only':True})['item']
                    self.assertEqual(note['state'],'saved');self.assertEqual(file['state'],'saved');self.assertEqual(bundle['state'],'saved');self.assertEqual(link['state'],'needs_content')
                    for call in (queue,capture,fetch,group):call.assert_not_called()
                self.assertTrue(service.archive.retrieve('tar samples'))
                # Pending-only startup recovery will not schedule intentionally saved records.
                self.assertFalse(any(item['state']=='pending' for item in service.archive.list()))
                with patch.object(ai,'summary_fields',return_value={'summary':'Generated on request','state':'ready'}):
                    service.queue(note['id'],force=True);wait(lambda:service.archive.get(note['id'])['state']=='ready')
            finally:service.close()

    def test_stage_timing_is_content_free_and_close_releases_waiters(self):
        jobs=SummaryJobs();jobs.enqueue('one',30,True)
        with jobs.session('one',short=True):
            ai.report('waiting_model');self.assertEqual(jobs.snapshot('one')['stage'],'waiting_model')
        value=jobs.snapshot('one');self.assertEqual(value['stage'],'done');self.assertGreaterEqual(value['elapsed_seconds'],value['model_seconds']);self.assertNotIn('text',value)
        jobs.close()
        with self.assertRaisesRegex(RuntimeError,'停止'):
            with jobs.session('stopped'):pass
        self.assertEqual(jobs.snapshot('stopped')['stage'],'stopped')
