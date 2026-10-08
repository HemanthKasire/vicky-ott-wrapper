import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('portal',Path(__file__).parents[1]/'torrent-portal.py')
portal=importlib.util.module_from_spec(spec);spec.loader.exec_module(portal)
class Emitted(Exception):
 def __init__(self,payload):self.payload=payload
class TVRequests(unittest.TestCase):
 def run_add(self,payload,torrent=None):
  config={'QB_SAVE_PATH':'/downloads/complete'}
  storage={'mounted':True,'usedBytes':10,'totalBytes':100,'availableBytes':90}
  with patch.object(portal,'validate_magnet',return_value='a'*40),patch.object(portal,'storage_status',return_value=storage),patch.object(portal,'find_torrent',return_value=torrent),patch.object(portal,'ensure_tv_series') as series,patch.object(portal,'qb_request',return_value='Ok.') as qb,patch.object(portal,'emit',side_effect=lambda p,*a:(_ for _ in ()).throw(Emitted(p))):
   try:portal.add_action(config,payload)
   except Emitted as result:return result.payload,series.call_args_list,qb.call_args_list
 def test_tv_uses_isolated_folder_and_category(self):
  result,series,calls=self.run_add({'magnet':'unused','mediaType':'show','tvdbId':123})
  self.assertTrue(result['queued']);self.assertEqual(series[0].args[1],123)
  self.assertEqual(calls[0].kwargs['form']['savepath'],'/downloads/tv')
  self.assertEqual(calls[0].kwargs['form']['category'],'portal-tv')
 def test_legacy_movies_keep_their_path(self):
  result,series,calls=self.run_add({'magnet':'unused'})
  self.assertTrue(result['queued']);self.assertFalse(series)
  self.assertEqual(calls[0].kwargs['form']['savepath'],'/downloads/complete')
 def test_existing_movie_is_not_reclassified_as_tv(self):
  result,_,calls=self.run_add({'magnet':'unused','mediaType':'show','tvdbId':123},{'category':''})
  self.assertEqual(result['status'],409);self.assertFalse(calls)
 def test_invalid_media_type_is_rejected(self):
  result,_,calls=self.run_add({'magnet':'unused','mediaType':'../../shows'})
  self.assertEqual(result['status'],400);self.assertFalse(calls)
 def test_existing_tv_is_not_reclassified_as_movie(self):
  result,_,calls=self.run_add({'magnet':'unused'},{'category':'portal-tv'})
  self.assertEqual(result['status'],409);self.assertFalse(calls)
 def test_manual_pack_skips_series_lookup(self):
  with tempfile.TemporaryDirectory() as tmp, patch.object(portal,'MANUAL_TV_DIR',Path(tmp)):
   result,series,calls=self.run_add({'magnet':'unused','mediaType':'show','manualTV':{'title':'Example Show','season':1,'episode':None}})
   self.assertTrue(result['queued']);self.assertFalse(series)
   self.assertEqual(calls[0].kwargs['form']['savepath'],'/downloads/tv-manual')
   self.assertEqual(calls[0].kwargs['form']['category'],'portal-tv-manual')
   record=json.loads((Path(tmp)/(('a'*40)+'.json')).read_text())
   self.assertEqual(record['title'],'Example Show');self.assertIsNone(record['episode'])
 def test_invalid_manual_season_does_not_add(self):
  result,series,calls=self.run_add({'magnet':'unused','mediaType':'show','manualTV':{'title':'Show','season':-1}})
  self.assertEqual(result['status'],400);self.assertFalse(series);self.assertFalse(calls)
if __name__=='__main__':unittest.main()
