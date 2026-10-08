import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
spec=importlib.util.spec_from_file_location('movies',Path(__file__).with_name('cleanup-movies.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MovieCleanupTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        self.downloads=self.root/'media/torrents/complete';self.downloads.mkdir(parents=True)
        self.movies=self.root/'media/movies';self.movies.mkdir(parents=True)
        self.movie=self.movies/'Example (2026).mkv'
        self.data=b'abcdefghijklmnopqrstuvwxyz012345'
        self.movie.write_bytes(self.data)
        self.files=[{'index':0,'name':'Example.mkv','size':len(self.data),'priority':1,'progress':1}]
        self.torrent={'hash':'a'*40,'category':'','save_path':'/downloads/complete','progress':1}
        self.config={'HOST_STORAGE_PATH':str(self.root),'HOST_MOVIES_PATH':str(self.movies)}
        self.portal=Mock();self.portal.is_exact_mount.return_value=True
        self.portal.get_torrents.return_value=[self.torrent]
        self.hashes=[hashlib.sha1(self.data[n:n+4]).hexdigest() for n in range(0,len(self.data),4)]
        def request(config,endpoint,**kwargs):
            if '/files?' in endpoint:return json.dumps(self.files)
            if '/properties?' in endpoint:return '{"piece_size":4}'
            if '/pieceHashes?' in endpoint:return json.dumps(self.hashes)
            return ''
        self.portal.qb_request.side_effect=request
    def proof(self):
        return m.proof(self.portal,self.config,self.torrent,self.files,m.library_index(self.movies))
    def test_already_moved_movie_verified_against_torrent(self):
        result=self.proof();self.assertEqual(result[0]['method'],'first-middle-last-torrent-pieces')
    def test_wrong_content_same_size_is_rejected(self):
        self.movie.write_bytes(b'x'*len(self.data))
        with self.assertRaises(ValueError):self.proof()
    def test_wrong_size_is_rejected(self):
        self.movie.write_bytes(b'short')
        with self.assertRaises(ValueError):self.proof()
    def test_hardlink_does_not_need_hash_api(self):
        os.link(self.movie,self.downloads/'Example.mkv')
        self.assertEqual(self.proof()[0]['method'],'hardlink')
        self.portal.qb_request.assert_not_called()
    def test_multi_video_requires_all_imported(self):
        self.files.append({'index':1,'name':'Other.mkv','size':99,'priority':1,'progress':1})
        with self.assertRaises(ValueError):self.proof()
    def test_incomplete_video_is_rejected(self):
        self.files[0]['progress']=.9
        with self.assertRaises(ValueError):self.proof()
    def test_tv_and_changed_paths_are_rejected(self):
        for key,value in [('category','portal-tv'),('save_path','/downloads/tv'),('hash','all'),('progress',.9)]:
            original=self.torrent[key];self.torrent[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.proof()
            self.torrent[key]=original
    def test_all_paths_checked_including_extras(self):
        self.files.append({'index':1,'name':'../outside.txt','size':0,'priority':0,'progress':0})
        with self.assertRaises(ValueError):self.proof()
    def test_symlink_sources_are_rejected(self):
        (self.downloads/'Example.mkv').symlink_to(self.movie)
        with self.assertRaises(ValueError):self.proof()
    def test_unavailable_hashes_keep_movie(self):
        self.hashes=[]
        with self.assertRaises(ValueError):self.proof()
    def test_piece_offsets_with_another_file(self):
        data=b'aaa'+self.data+b'zzzz'
        hashes=[hashlib.sha1(data[n:n+4]).hexdigest() for n in range(0,len(data),4)]
        self.assertTrue(m.sampled_pieces(self.movie,3,len(self.data),len(data),4,hashes))
    def test_piece_size_is_bounded(self):
        with self.assertRaises(ValueError):m.sampled_pieces(self.movie,0,len(self.data),len(self.data),m.MAX_PIECE+1,[])
    def test_delete_retains_library_and_preview_does_not_delete(self):
        with patch.object(m,'STATE',self.root/'state'):
            self.assertEqual(m.cleanup(self.portal,self.config,True)[0]['action'],'verified')
            self.assertFalse(any(call.args[1].endswith('/delete') for call in self.portal.qb_request.call_args_list))
            self.assertEqual(m.cleanup(self.portal,self.config)[0]['action'],'delete-requested')
        deletion=[call for call in self.portal.qb_request.call_args_list if call.args[1].endswith('/delete')]
        self.assertEqual(deletion[0].kwargs['form'],{'hashes':'a'*40,'deleteFiles':'true'})
        self.assertEqual(self.movie.read_bytes(),self.data)
    def test_mount_missing_blocks_deletion(self):
        self.portal.is_exact_mount.return_value=False
        with self.assertRaises(ValueError):m.cleanup(self.portal,self.config)
        self.portal.qb_request.assert_not_called()
    def test_failed_verification_never_deletes(self):
        self.movie.unlink()
        self.assertEqual(m.cleanup(self.portal,self.config)[0]['action'],'kept')
        self.assertFalse(any(call.args[1].endswith('/delete') for call in self.portal.qb_request.call_args_list))

if __name__=='__main__':unittest.main()
