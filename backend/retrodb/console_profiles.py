"""Curated, reviewable console profiles. No third-party API credentials required."""
PROFILES = {
    "playstation": {
        "uk":"29 September 1995","jp":"3 December 1994","us":"9 September 1995",
        "predecessor":None,"successor":"playstation-2","media":"CD-ROM","cpu":"MIPS R3000A-compatible, 32-bit, ~33.9 MHz",
        "memory":"2 MB main RAM, 1 MB frame buffer, 512 KB sound RAM",
        "video":"RF (via adapter), composite, RGB SCART, S-Video (region/model dependent)",
        "audio":"Stereo analogue RCA / AV Multi Out; digital audio on selected revisions",
        "ports":"2 controller ports; 2 memory-card slots",
        "storage":"External memory cards: 15 game blocks per standard card",
        "generation":"Fifth","overview":"Sony's first PlayStation established CD-based 3D gaming as a mass-market format.",
        "revisions":"Early SCPH-100x units through later cost-reduced revisions; the compact PS one arrived in 2000.",
        "accessories":"Dual Analog and DualShock controllers, multitap, memory cards, link cable, light guns, steering wheels.",
        "guides":["Composite versus RGB SCART video setup","Memory card care and backup","Disc compatibility and region basics"]
    },
    "playstation-2": {
        "uk":"24 November 2000","jp":"4 March 2000","us":"26 October 2000",
        "predecessor":"playstation","successor":"playstation-3","media":"DVD-ROM, CD-ROM, DVD-Video",
        "cpu":"Emotion Engine (~294 MHz initial models)","memory":"32 MB RDRAM",
        "video":"Composite, RGB SCART, S-Video, component YPbPr; RF via adapter",
        "audio":"Analogue stereo, optical S/PDIF digital output",
        "ports":"2 controller ports; 2 memory-card slots; USB; expansion options vary by revision",
        "storage":"8 MB standard memory cards; expansion-bay HDD on compatible fat models",
        "generation":"Sixth","overview":"Sony's DVD-capable successor combined a large software library with backwards compatibility for many original PlayStation games.",
        "revisions":"Original fat models, expansion-bay variants, and compact slim redesigns with different network and storage capabilities.",
        "accessories":"DualShock 2, multitap, EyeToy, network adapter, HDD, steering wheels, light guns.",
        "guides":["RGB SCART and component output","Network adapter and online play","Memory card and Free McBoot basics"]
    },
    "playstation-3": {
        "uk":"23 March 2007","jp":"11 November 2006","us":"17 November 2006",
        "predecessor":"playstation-2","successor":None,"media":"Blu-ray Disc, DVD, CD",
        "cpu":"Cell Broadband Engine","memory":"256 MB XDR system + 256 MB GDDR3 graphics",
        "video":"HDMI, analogue AV Multi Out (including component on supported cables)",
        "audio":"HDMI multichannel, optical digital, analogue stereo",
        "ports":"USB ports vary by revision; wireless Bluetooth controllers",
        "storage":"Replaceable internal 2.5-inch SATA HDD on retail models",
        "generation":"Seventh","overview":"The PlayStation 3 brought Blu-ray playback, high-definition gaming and PlayStation Network to Sony's console family.",
        "revisions":"Original fat hardware, slimmer revisions, and super-slim top-loading models; PS2 backwards compatibility differs significantly.",
        "accessories":"Sixaxis, DualShock 3, PlayStation Eye, Move, Bluetooth headset, steering wheels.",
        "guides":["HDMI and audio setup","Internal drive replacement","Model-specific backward compatibility"]
    },
    "playstation-portable": {
        "uk":"1 September 2005","jp":"12 December 2004","us":"24 March 2005",
        "predecessor":None,"successor":None,"media":"UMD optical discs; Memory Stick PRO Duo",
        "cpu":"MIPS-based Allegrex, up to 333 MHz","memory":"32 MB RAM on PSP-1000; 64 MB on PSP-2000 and later",
        "video":"Built-in LCD; composite/component TV output on supported later models",
        "audio":"Stereo speakers, 3.5 mm headphone output",
        "ports":"Integrated controls; USB; Wi-Fi (802.11b on supported retail models)",
        "storage":"Memory Stick Duo / PRO Duo; internal storage varies on PSP Go",
        "generation":"Seventh","overview":"Sony's first PlayStation handheld combined portable 3D gaming, UMD media and wireless multiplayer.",
        "revisions":"PSP-1000, PSP-2000, PSP-3000, digital-only PSP Go, and PSP Street/E1000 with notable hardware and connectivity differences.",
        "accessories":"Memory Stick PRO Duo, protective cases, TV-output cables, camera, GPS accessory, headphones.",
        "guides":["Memory Stick preparation","UMD and digital games","Wireless network compatibility"]
    }
}
