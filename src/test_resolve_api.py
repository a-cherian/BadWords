import sys
sys.path.append('/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript')
import imp
resolve = imp.load_dynamic('fusionscript', '/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so').scriptapp('Resolve')
projectManager = resolve.GetProjectManager()
project = projectManager.GetCurrentProject()
mediaPool = project.GetMediaPool()
folder = mediaPool.GetRootFolder()
items = folder.GetClipList()
print("MediaPool methods:", [m for m in dir(mediaPool) if not m.startswith('_')])
print("Folder methods:", [m for m in dir(folder) if not m.startswith('_')])
timeline = project.GetCurrentTimeline()
print("Timeline methods:", [m for m in dir(timeline) if not m.startswith('_')])
