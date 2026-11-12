import json
import tempfile
import unittest
from unittest.mock import patch
from secretary import semantic,knowledge_chat,company_ai
from secretary.core import Archive
from secretary.server import Service


def vectors(config,inputs,**kwargs):
    # Different wording, with no shared terms, represents the same topic.
    return [[1.,0.,0.] if any(word in text for word in ('续航','省电','battery','energy')) else [0.,1.,0.] for text in inputs]


class SemanticTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.archive=Archive(self.temp.name)
        self.index=semantic.SemanticIndex(self.archive)
        # Drive batches explicitly to make race tests deterministic.
        self.no_worker=patch.object(self.index,'start');self.no_worker.start()
        self.index.save(dict(semantic.DEFAULT,enabled=True))

    def tearDown(self):
        self.index.close();self.no_worker.stop();self.temp.cleanup()

    def test_semantic_only_match_and_hybrid_sources(self):
        match,_=self.archive.add('出行笔记','battery life improves with energy saving')
        other,_=self.archive.add('天文','Galaxy research and observation')
        self.assertEqual(self.archive.retrieve('如何省电'),[])
        with patch('secretary.semantic.embed',side_effect=vectors):
            self.assertEqual(self.index.build_batch(),2)
            hits=knowledge_chat.retrieve(self.archive,['如何省电'],semantic=self.index)
        self.assertEqual([hit['item_id'] for hit in hits],[match])
        self.assertNotIn(other,[hit['item_id'] for hit in hits])
        self.assertEqual(self.index.status()['indexed'],2)

    def test_incremental_edit_trash_restore_and_delete(self):
        item,_=self.archive.add('Battery','battery life')
        with patch('secretary.semantic.embed',side_effect=vectors):
            self.index.build_batch();self.assertEqual(self.index.status()['indexed'],1)
            self.archive.update(item,text='Galaxy astronomy')
            self.assertEqual(self.index.status()['indexed'],0)
            self.index.build_batch();self.assertEqual(self.index.search(['省电']),[])
            self.archive.trash_item(item,self.archive.get(item)['updated'])
            self.assertEqual(self.index.status()['indexed'],0)
            self.assertEqual(self.index.search(['Galaxy']),[])
            self.archive.restore_item(item)
            self.index.build_batch();self.assertEqual(self.index.status()['indexed'],1)
            self.archive.update(item,title='Renamed')
            self.assertEqual(self.index.status()['indexed'],0)
            self.index.build_batch()
            self.archive.delete(item,self.archive.get(item)['updated'])
            with self.archive.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM semantic_vectors').fetchone()[0],0)

    def test_existing_library_reopens_with_cache(self):
        self.archive.add('Battery','battery')
        with patch('secretary.semantic.embed',side_effect=vectors):self.index.build_batch()
        reopened=Archive(self.temp.name,recover=False)
        self.assertEqual(self.index.status()['indexed'],1)
        with reopened.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM semantic_vectors').fetchone()[0],1)

    def test_edits_or_rebuild_during_embedding_do_not_commit_stale_vectors(self):
        item,_=self.archive.add('Battery','battery')
        def mutate(config,inputs,**kwargs):
            self.archive.update(item,text='Changed astronomy')
            return vectors(config,inputs)
        with patch('secretary.semantic.embed',side_effect=mutate):self.assertEqual(self.index.build_batch(),0)
        def rebuild(config,inputs,**kwargs):
            self.index.save(config,rebuild=True)
            return vectors(config,inputs)
        with patch('secretary.semantic.embed',side_effect=rebuild):self.assertEqual(self.index.build_batch(),0)
        self.assertEqual(self.index.status()['indexed'],0)

    def test_switching_models_invalidates_cache_and_off_switch_preserves_it(self):
        self.archive.add('Battery','battery')
        with patch('secretary.semantic.embed',side_effect=vectors):self.index.build_batch()
        self.index.save(dict(semantic.DEFAULT,enabled=False))
        with patch('secretary.semantic.embed') as embed:
            self.assertEqual(self.index.search(['省电']),[]);embed.assert_not_called()
        self.assertEqual(self.index.status()['indexed'],1)
        self.index.save(dict(semantic.DEFAULT,enabled=True,model='other-embedding'))
        self.assertEqual(self.index.status()['indexed'],0)

    def test_local_service_failure_keeps_keyword_results_with_notice(self):
        item,_=self.archive.add('Battery','battery')
        with patch('secretary.semantic.embed',side_effect=vectors):self.index.build_batch()
        notice=[]
        with patch('secretary.semantic.embed',side_effect=RuntimeError('offline')):
            hits=knowledge_chat.retrieve(self.archive,['battery'],semantic=self.index,notice=notice)
        self.assertEqual(hits[0]['item_id'],item)
        self.assertIn('关键词',notice[0])

    def test_dimension_change_does_not_silently_mix_vectors(self):
        self.archive.add('Battery','battery')
        with patch('secretary.semantic.embed',return_value=[[1.,0.,0.]]):self.index.build_batch()
        with patch('secretary.semantic.embed',return_value=[[1.,0.]]):
            with self.assertRaisesRegex(ValueError,'重建'):self.index.search(['省电'])

    def test_loopback_only_and_vector_validation(self):
        for url in ('https://example.com','http://192.168.1.1','http://127.0.0.1@evil.test','http://localhost/path','http://localhost:0','file:///tmp/a'):
            with self.assertRaises(ValueError):semantic.normalize(dict(semantic.DEFAULT,base_url=url))
        self.assertEqual(semantic.normalize(dict(semantic.DEFAULT,base_url='http://localhost:11434'))['base_url'],'http://127.0.0.1:11434')
        for vector in ([],[0.,0.],[float('nan')],[float('inf')],[True],['1']):
            with self.assertRaises(ValueError):semantic.unit(vector)
        self.assertEqual(semantic.unit([3.,4.]),[.6,.8])

    def test_embedding_protocol_validates_response_and_disables_truncation(self):
        with patch('secretary.semantic.urllib.request.build_opener') as builder:
            response=builder.return_value.open.return_value.__enter__.return_value
            response.read.return_value=json.dumps({'embeddings':[[3.,4.]]}).encode()
            self.assertEqual(semantic.embed(semantic.DEFAULT,['sample']),[[.6,.8]])
            request=builder.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/embed')
            self.assertEqual(json.loads(request.data),dict(model='bge-m3',input=['sample'],truncate=False))
            for invalid in ({'embeddings':[]},{'embeddings':[[0.,0.]]},{'embeddings':[[float('nan')]]},{'embeddings':'bad'}):
                response.read.return_value=json.dumps(invalid).encode()
                with self.assertRaises(ValueError):semantic.embed(semantic.DEFAULT,['sample'])

    def test_source_page_metadata_survives_vector_retrieval(self):
        item,_=self.archive.add('Pages','astronomy')
        origin={'name':'guide.pdf','page':7,'attachment_id':'fixture'}
        with self.archive.db() as db:db.execute('INSERT INTO chunks(item_id,position,text,origin) VALUES (?,?,?,?)',(item,-1,'battery life',json.dumps(origin)))
        with patch('secretary.semantic.embed',side_effect=vectors):
            self.index.build_batch();hits=self.index.search(['省电'])
        self.assertEqual(hits[0]['origin'],origin)

    def test_semantic_only_company_match_still_requires_answer_model_confirmation(self):
        self.index.close()
        with patch.object(semantic.SemanticIndex,'start'):service=Service(self.temp.name)
        try:
            service.archive.configure('codex',False);service.archive.set_company_mode(True)
            item,_=service.archive.add('Private report','battery life')
            company_ai.mark(service.archive,item)
            with patch.object(service.semantic,'start'),patch('secretary.semantic.embed',side_effect=vectors):
                service.semantic.build_batch()
                with patch('secretary.ai.run',return_value='{"queries":["省电"]}') as model:
                    with self.assertRaises(company_ai.ApprovalRequired):service.ask_library('如何省电')
                    self.assertEqual(model.call_count,1)
        finally:service.close()


if __name__=='__main__':unittest.main()
