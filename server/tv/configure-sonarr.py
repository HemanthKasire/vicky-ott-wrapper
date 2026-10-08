import json,subprocess,time,urllib.request,xml.etree.ElementTree as ET
key=ET.parse('/home/ubuntu/sonarr/config/config.xml').getroot().findtext('ApiKey')
ip=subprocess.check_output(['docker','inspect','qbittorrent','--format','{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}'],text=True).split()[0]
def api(path,method='GET',data=None):
 req=urllib.request.Request(f'http://{ip}:8989/api/v3/{path}',method=method,data=json.dumps(data).encode() if data is not None else None,headers={'X-Api-Key':key,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
for attempt in range(30):
 try:
  print('Sonarr version',api('system/status')['version']);break
 except OSError:time.sleep(2)
else:raise SystemExit('Sonarr startup did not complete')
root='/data/shows'
if not any(x['path']==root for x in api('rootfolder')):api('rootfolder','POST',{'path':root})
naming=api('config/naming')
naming.update({'renameEpisodes':True,'seasonFolderFormat':'Season {season:00}','seriesFolderFormat':'{Series TitleYear}','standardEpisodeFormat':'{Series Title} - S{season:00}E{episode:00} - {Episode CleanTitle} [{Quality Full}]','dailyEpisodeFormat':'{Series Title} - {Air-Date} - {Episode CleanTitle} [{Quality Full}]'})
api('config/naming','PUT',naming)
media=api('config/mediamanagement');media.update({'copyUsingHardlinks':True,'setPermissionsLinux':True,'chmodFolder':'775','chownGroup':'1001'});api('config/mediamanagement','PUT',media)
download=api('config/downloadclient');download.update({'enableCompletedDownloadHandling':True,'checkForFinishedDownloadInterval':1});api('config/downloadclient','PUT',download)
clients=api('downloadclient')
if not any(c['name']=='Portal TV qBittorrent' for c in clients):
 schema=next(c for c in api('downloadclient/schema') if c['implementation']=='QBittorrent')
 schema.update({'name':'Portal TV qBittorrent','enable':True,'priority':1,'removeCompletedDownloads':False,'removeFailedDownloads':False})
 values={'host':'127.0.0.1','port':8082,'useSsl':False,'tvCategory':'portal-tv','tvImportedCategory':'','recentTvPriority':0,'olderTvPriority':0,'initialState':0}
 for f in schema['fields']:
  if f['name'] in values:f['value']=values[f['name']]
 api('downloadclient/test','POST',schema)
 api('downloadclient','POST',schema)
if not any(m['remotePath']=='/downloads/' for m in api('remotepathmapping')):
 api('remotepathmapping','POST',{'host':'127.0.0.1','remotePath':'/downloads/','localPath':'/data/torrents/'})
# Shared container network keeps qBittorrent's existing localhost-only API authentication intact.
subprocess.run(['docker','exec','qbittorrent','curl','-fsS','-X','POST','--data-urlencode','category=portal-tv','--data-urlencode','savePath=/downloads/tv','http://127.0.0.1:8082/api/v2/torrents/editCategory'],check=True,capture_output=True)
print('Configured root, naming, hardlinks, download client and path mapping')
print('Health',[(x.get('type'),x.get('message')) for x in api('health')])
