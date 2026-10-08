import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
spec = importlib.util.spec_from_file_location('cleanup', Path(__file__).with_name('cleanup-tv.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'media/torrents/tv/Show/S01E01.mkv'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'episode')
        self.target = self.root / 'media/shows/Show/Season 01/E01.mkv'
        self.target.parent.mkdir(parents=True)
        os.link(self.source, self.target)
        self.torrent = {'category':'portal-tv', 'hash':'a'*40, 'progress':1, 'save_path':'/downloads/tv'}
        self.files = [{'name':'Show/S01E01.mkv', 'size':7, 'progress':1, 'priority':1}]
    def verify(self):
        return c.proof(self.torrent, self.files, self.root, c.show_index(self.root / 'media/shows'))
    def test_hardlink_verified(self):
        self.assertEqual(len(self.verify()), 1)
    def test_copy_is_not_proof(self):
        self.target.unlink();self.target.write_bytes(b'episode')
        with self.assertRaises(ValueError):self.verify()
    def test_any_unimported_episode_blocks_pack(self):
        other=self.source.with_name('S01E02.mkv');other.write_bytes(b'episode')
        self.files.append({'name':'Show/S01E02.mkv','size':7,'progress':1,'priority':1})
        with self.assertRaises(ValueError):self.verify()
    def test_incomplete_episode(self):
        self.files[0]['progress']=.5
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_category_or_location(self):
        for key,value in [('category',''),('save_path','/downloads/complete'),('hash','all'),('progress',.9)]:
            with self.subTest(key=key):
                original=self.torrent[key];self.torrent[key]=value
                with self.assertRaises(ValueError):self.verify()
                self.torrent[key]=original
    def test_traversal_and_symlink(self):
        for name in ['../outside.mkv','/etc/file.mkv']:
            with self.assertRaises(ValueError):c.safe_path(self.source.parent,name)
        link=self.source.parent/'link.mkv';link.symlink_to(self.source)
        with self.assertRaises(ValueError):c.safe_path(self.source.parent,'link.mkv')
    def test_delete_original_preserves_show(self):
        portal=Mock();portal.get_torrents.return_value=[self.torrent];portal.is_exact_mount.return_value=True
        def request(config,endpoint,**kwargs):
            if '/files?' in endpoint:return json.dumps(self.files)
            if endpoint.endswith('/delete'):
                self.assertEqual(kwargs['form']['deleteFiles'],'true');self.source.unlink()
            return ''
        portal.qb_request.side_effect=request
        with patch.object(c,'STATE',self.root/'state'):
            result=c.cleanup(portal,{'HOST_STORAGE_PATH':str(self.root)})
        self.assertEqual(result[0]['action'],'delete-requested')
        self.assertEqual(self.target.read_bytes(),b'episode');self.assertFalse(self.source.exists())
    def test_preview_does_not_mutate(self):
        portal=Mock();portal.get_torrents.return_value=[self.torrent];portal.is_exact_mount.return_value=True
        portal.qb_request.return_value=json.dumps(self.files)
        self.assertEqual(c.cleanup(portal,{'HOST_STORAGE_PATH':str(self.root)},True)[0]['action'],'verified')
        self.assertTrue(self.source.exists())
        self.assertTrue(all('method' not in call.kwargs for call in portal.qb_request.call_args_list))
    def test_manual_requires_import_record(self):
        self.torrent.update(category='portal-tv-manual',save_path='/downloads/tv-manual')
        portal=Mock();portal.get_torrents.return_value=[self.torrent];portal.is_exact_mount.return_value=True
        record=self.root/'record.json';record.write_text('{"state":"waiting"}');portal.manual_tv_path.return_value=record
        result=c.cleanup(portal,{'HOST_STORAGE_PATH':str(self.root)})
        self.assertEqual(result[0]['action'],'kept')
        self.assertFalse(any(call.args[1].endswith('/delete') for call in portal.qb_request.call_args_list))
if __name__=='__main__':unittest.main()
