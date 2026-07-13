import sys
import imp
resolve = imp.load_dynamic('fusionscript', '/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so').scriptapp('Resolve')
projectManager = resolve.GetProjectManager()
project = projectManager.GetCurrentProject()
media_pool = project.GetMediaPool()

tl = project.GetCurrentTimeline()
print(f"Current Timeline: {tl.GetName()}")

# get root folder, search for timeline item
folder = media_pool.GetRootFolder()
items = folder.GetClipList()
source_item = None
for item in items:
    if item.GetName() == tl.GetName():
        source_item = item
        break

print(f"Source Item Type: {source_item.GetClipProperty('Type') if source_item else None}")

# Create new timeline
new_tl = media_pool.CreateEmptyTimeline("Test Append Timeline 3")
project.SetCurrentTimeline(new_tl)

offset = tl.GetStartFrame()
print(f"Timeline Start Frame: {offset}")

clip1 = {"mediaPoolItem": source_item, "startFrame": 0, "endFrame": 50}
clip2 = {"mediaPoolItem": source_item, "startFrame": offset + 100, "endFrame": offset + 150}

print("Appending clip1 (0-based)...")
res1 = media_pool.AppendToTimeline([clip1])
print(f"Result 1: {res1}")
print(f"Timeline items count: {new_tl.GetItemListInTrack('video', 1)}")

print("Appending clip2 (absolute-based)...")
res2 = media_pool.AppendToTimeline([clip2])
print(f"Result 2: {res2}")
print(f"Timeline items count: {new_tl.GetItemListInTrack('video', 1)}")

