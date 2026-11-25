# Launcher assets

Generated with the built-in image_gen tool, 25 November 2026. Android density exports are resampled from the generated masters; no inset card or pre-rounded launcher mask is baked in.

Saved masters:
- branding/lumi-tv-banner.png
- branding/lumi-launcher.png

Runtime assets: drawable-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/banner.png; mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png; mipmap-anydpi-v26/ic_launcher.xml with white background and a safe-area foreground.

Exact prompts:

## tv_banner

Edit the supplied Lumi Android TV banner. Preserve the exact recognizable glossy multicolored glass-petal flower logo and lowercase word 'lumi'. Create a polished FULL-BLEED landscape 16:9 Android TV launcher banner, filling the entire canvas edge-to-edge. Use a clean bright ivory-white background across the WHOLE image, no inset card, no rounded square around the flower, no dark outer frame, no empty surrounding margins. Large flower at left occupying most of the banner height (about 80% height) and very large dark lowercase 'lumi' at right, simple Apple-like typography. Remove the Russian subtitle completely. Keep entire flower and word within a modest 8% safe margin. The final image itself is the launcher card, not a card pictured inside another image. Flat orthographic finished brand asset, crisp beautiful glass petals, no device mockup, no shadows outside canvas. Exact wide 16:9 composition.

## tv_icon

Edit this existing Lumi app launcher icon. Preserve the recognizable exact glossy glass-petal flower logo with black grey yellow lime green cyan and blue petals. Redesign as a full-bleed SQUARE Android launcher icon: pure ivory-white background fills the entire square edge to edge, a very large centered flower takes approximately 78% of the canvas width and height. Remove ALL text, subtitle, dark outer background, small white rounded-square inset and card framing. Do not put one small icon inside another icon. Just the single large detailed glass flower on a white full-bleed square background, no border and no pre-rounded outer corners; Android applies its own mask. Crisp clean faithful logo, balanced petals, strong recognizable shape at television distance.


0.7.2: the same approved full-bleed banner is also exported to mipmap-*/lumi_tv_banner.png and mipmap-nodpi/lumi_tv_banner.png. The manifest uses these resources on the application, MainActivity and a new LumiTvLauncher activity-alias, so launcher artwork is rediscovered after upgrade. No new artwork was generated.

0.7.3: export the approved banner at 496x280 as drawable/lumi_vision_tile.png. Per Huawei Vision S integration guidance, the real launcher MainActivity uses it for icon, banner and logo with CATEGORY_LAUNCHER; application/settings keep the square icon. Reference: https://forums.developer.huawei.com/forumPortal/en/topic/0202585440415910074 . No new artwork was generated.

0.7.4: drawable/lumi_launcher_card.png reuses the same 496x280 image. Application and MainActivity now both reference it as icon, logo and banner. The application no longer exposes the square adaptive icon as a competing launcher source. APK verification checks application/normal/Leanback launcher icon selection and actual PNG dimensions.
