import importlib.util
from pathlib import Path
import os
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('portal',Path(__file__).parents[1]/'torrent-portal.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class ManualTV(unittest.TestCase):
 def test_optional_episode(self):
  self.assertEqual(p.validate_manual_tv({'title':'Example Show','season':1})['episode'],None)
 def test_invalid_title_and_numbers(self):
  for detail in [{'title':'../Escape','season':1},{'title':'Show','season':True},{'title':'Show','season':1,'episode':0}]:
   with self.assertRaises(ValueError):p.validate_manual_tv(detail)
 def test_filename_formats(self):
  for name,expected in [('Show_S01E02.mkv','E02'),('Show.1x03.mkv','E03'),('Episode 04.mkv','E04'),('E05.mkv','E05'),('06 - Title.mkv','E06'),('07.mkv','E07'),('Show.S01E08E09.mkv','E08E09'),('Show.S01E01-E03.mkv','E01E02E03')]:
   self.assertEqual(p.episode_suffix(name,1),expected)
 def test_unknown_and_wrong_season(self):
  for name in ['Show.2024.1080p.mkv','Show.S02E01.mkv']:
   with self.assertRaises(ValueError):p.episode_suffix(name,1)
 def arrange(self,root,names):
  source=root/'media/torrents/tv-manual';source.mkdir(parents=True)
  (root/'media/shows').mkdir()
  files=[]
  for name in names:
   path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
   files.append({'name':name,'progress':1,'priority':1})
  return source,files
 def test_pack_hardlinks_without_moving_sources(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source,files=self.arrange(root,['Pack/Show.S01E01.mkv','Pack/Show.S01E02.mp4'])
   subtitle=source/'Pack/Show.S01E01.en.srt';subtitle.write_text('subtitle')
   r={'title':'Example Show','season':1,'episode':None}
   self.assertEqual(p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},r,files),2)
   self.assertEqual(r['state'],'imported')
   for episode,ext in [(1,'mkv'),(2,'mp4')]:
    dst=root/f'media/shows/Example Show/Season 01/Example Show - S01E{episode:02}.{ext}'
    self.assertTrue(os.path.samefile(source/files[episode-1]['name'],dst))
   self.assertTrue((root/'media/shows/Example Show/Season 01/Example Show - S01E01.en.srt').exists())
   self.assertEqual(p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},r,files),0)
 def test_single_episode_override(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source,files=self.arrange(root,['badname.mkv'])
   r={'title':'Example Show','season':2,'episode':5}
   self.assertEqual(p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},r,files),1)
   self.assertTrue((root/'media/shows/Example Show/Season 02/Example Show - S02E05.mkv').exists())
 def test_override_rejects_pack(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);_,files=self.arrange(root,['S01E01.mkv','S01E02.mkv'])
   with self.assertRaises(ValueError):p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},{'title':'Show','season':1,'episode':1},files)
 def test_unknown_episode_keeps_source(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source,files=self.arrange(root,['unclear.mkv'])
   r={'title':'Show','season':1,'episode':None}
   self.assertEqual(p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},r,files),0)
   self.assertEqual(r['state'],'needs-review');self.assertTrue((source/'unclear.mkv').exists())
 def test_never_overwrites_existing_episode(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);_,files=self.arrange(root,['S01E01.mkv'])
   target=root/'media/shows/Show/Season 01/Show - S01E01.mkv';target.parent.mkdir(parents=True);target.write_bytes(b'original')
   r={'title':'Show','season':1,'episode':None}
   self.assertEqual(p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},r,files),0)
   self.assertEqual(target.read_bytes(),b'original');self.assertEqual(r['state'],'needs-review')
 def test_source_path_traversal_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);_,_=self.arrange(root,[])
   outside=root/'S01E01.mkv';outside.write_bytes(b'outside')
   r={'title':'Show','season':1,'episode':None}
   files=[{'name':'../../../S01E01.mkv','priority':1,'progress':1}]
   self.assertEqual(p.link_manual_tv({'HOST_STORAGE_PATH':str(root)},{'save_path':'/downloads/tv-manual'},r,files),0)
   self.assertEqual(r['state'],'needs-review')
if __name__=='__main__':unittest.main()
