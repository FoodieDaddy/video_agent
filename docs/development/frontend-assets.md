# 前端图片资产记录

本文件记录项目使用的生成式图片资产及实际提示词，便于复核、替换和追溯。图片来自内置 `image_gen` 工具；本次未使用项目 Provider、项目密钥、外部 API 脚本或 CLI fallback。

## 雨夜旧书店电影画面

- 项目路径：`web/assets/rainy-bookstore.png`
- 用途：网页首页主视觉与分镜缩略图；仅为演示视觉素材，不代表项目已经完成真实视频生产。
- 生成日期：2026-11-04。
- 生成方式：内置 `image_gen`，根据下面的实际提示词生成一张原创电影画面，无参考图片。
- 文件格式：PNG，不透明背景。
- 实测尺寸：1900 × 828 像素，宽高比约 2.295:1。
- 文件大小：2,055,552 字节。
- SHA-256：`8ce4af3bd6998866f492d3746c7dd73f7efbea7f5392baf7a21856d81228e8f6`
- 工具原始文件：`/Users/happy/.codex/generated_images/01a1a675-73d2-7ac3-a247-35b78d2c28d6/exec-85b7cbb4-e126-4456-9204-c138cae7b76d.png`。
- 保存处理：将工具生成的 PNG 原样复制到项目，没有裁切、重绘或覆盖其他资产；保留工具原始文件。
- 已核对：雨夜中国旧书店外景、暖琥珀橱窗、深青阴影、湿地倒影、右侧撑伞女子背影，左侧暗部留白；未见可读文字、标志、水印或 UI。
- 页面使用建议：保留全画幅或以右侧人物作为裁切重点；文字可叠在左侧暗部，避免覆盖人物与书店橱窗。

### 实际生成提示词

以下内容与提交给内置工具的提示词一致：

```text
Use case: photorealistic-natural
Asset type: Original cinematic still for a film production website hero and storyboard thumbnail; generate only the photograph, no webpage or UI.
Primary request: A Chinese old-bookshop street exterior at night in the rain, with warm amber shop-window light, deep teal shadows, and a single woman holding an umbrella seen from behind on the right side.
Scene/backdrop: An intimate old Chinese city street outside a used bookstore. Rain-wet pavement reflects the glowing shop windows. Subtle shelves and books are visible through the warm glass; any signage is blank or absent.
Style/medium: Photorealistic cinema film photography, tactile materials, restrained independent literary mystery-film mood, fine natural film grain, realistic light and rain.
Composition/framing: Very wide landscape frame, approximately 2.3:1 aspect ratio. Keep the left 45 percent dark, calm and uncluttered for later website text overlay. Put the shop-window glow toward the middle-right and the woman's umbrella silhouette close to the right third. Eye-level wide establishing shot, convincing spatial depth.
Lighting/mood: Quiet rainy night; practical warm amber interior lights against deep teal-blue exterior shadow, reflective wet ground, subtle mist, restrained contrast.
Constraints: One original cinematic image. Only one person, seen from behind. No readable text, no characters or lettering, no logo, no watermark, no borders, no UI, no collage. Preserve clean dark negative space on the left.
```
