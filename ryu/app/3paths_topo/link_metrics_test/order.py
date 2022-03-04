
import os
import video_voip_transmission_2link as test

for i in range(1,3):
    test.ttest(i)
   # os.system("sudo python video_voip_transmission_2link.py")
    os.system("cp output.ts ./output/video/2link_received_video/received_video%s.ts"%i)
    os.remove("output.ts")
    os.system("sudo mn -c")
