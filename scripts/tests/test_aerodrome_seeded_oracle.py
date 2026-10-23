"""Development harness guards; no network or PostgreSQL in these tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('seeded',Path(__file__).parents[1]/'aerodrome-seeded-oracle.py')
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)

class Guards(unittest.TestCase):
    def test_windows_are_twenty_bounded_and_useful(self):
        w=M.windows();self.assertEqual(len(w),20)
        self.assertEqual(sum(x['stop_exclusive']-x['from'] for x in w),20000)
        self.assertTrue(all(x['stop_exclusive']-x['from']==1000 for x in w))
        self.assertNotIn(13902663,[x['from'] for x in w])
        self.assertTrue(any(x['from']<13909327<x['stop_exclusive'] for x in w))
        self.assertEqual(len({x[k]-1 for x in w for k in ('from','stop_exclusive')}),23)

    def test_sealed_publication_never_clobbers(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'complete.json';M.sealed(p,{'ok':True});before=p.read_bytes()
            with self.assertRaises(ValueError):M.sealed(p,{'ok':False})
            self.assertEqual(p.read_bytes(),before)
            self.assertFalse(p.with_name('complete.json.partial').exists())

    def test_existing_partial_refuses_without_final_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'complete.json';p.with_name('complete.json.partial').write_bytes(b'failed attempt')
            with self.assertRaises(FileExistsError):M.sealed(p,{'ok':True})
            self.assertFalse(p.exists())

    def test_pins_refuse_symlinks_and_detect_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';p.write_bytes(b'one');old=M.pin(p);p.write_bytes(b'two')
            self.assertNotEqual(M.pin(p),old)
            link=Path(d)/'link';link.symlink_to(p)
            with self.assertRaises(ValueError):M.pin(link)

    def test_canonical_json_retains_typed_field_order(self):
        self.assertEqual(M.canonical({'block_number':1,'block_hash':[1]}),b'{\n  "block_number": 1,\n  "block_hash": [\n    1\n  ]\n}\n')
        self.assertNotEqual(M.canonical({'block_hash':[1],'block_number':1}),M.canonical({'block_number':1,'block_hash':[1]}))

    def test_reused_comparison_requires_exact_window_plan_and_scope(self):
        window={'from':100,'stop_exclusive':110}
        result={'format':'pinax.aerodrome.hermetic-oracle-comparison/v1','plan_sha256':'aa'*32,
                'from':100,'stop_exclusive':110,'blocks':10,'full_producer_cache_matches':True,
                'every_triggered_block_poi_matches':True,'final_sql_visible_state_matches':True,
                'whole_envelope_mask':['compatibility_id'],'loadable':False,'production_qualified':False}
        M.validate_result(window,'aa'*32,result)
        for key,value in [('from',101),('stop_exclusive',111),('plan_sha256','bb'*32),
                          ('final_sql_visible_state_matches',False),('whole_envelope_mask',['compatibility_id','operations']),
                          ('loadable',True),('production_qualified',True),('full_producer_cache_matches',1)]:
            with self.subTest(key=key):
                changed={**result,key:value}
                with self.assertRaises(ValueError):M.validate_result(window,'aa'*32,changed)

if __name__=='__main__':unittest.main()
