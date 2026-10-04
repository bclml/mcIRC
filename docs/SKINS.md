# Skins

A skin is a picture. mcIRC puts it across the top of the window and takes the colours of the chat panes (text area, window list, name list, input line) from it,
so any image makes a usable skin. Pick one in **Options > Display > Skin**; choose **None** to go back to the plain colour themes.

## Make one in a minute

1. Open the `skins` folder next to `mcIRC.py`.
2. Drop a picture in it: PNG, JPG, GIF or BMP. A wide one (about 1400 x 56) looks best, but any size works.
3. Options > Display > Skin > pick its name. That's it.

## A skin with a folder (more control)

```
skins/My Skin/banner.png      the picture (banner.jpg / .gif / .bmp also work)
skins/My Skin/skin.json       optional
```

`skin.json`, every key optional:

```json
{
  "banner_height": 56,
  "mode": "cover",
  "base": "Night",
  "theme": { "pane_bg": "#112233", "sel_bg": "#336699" }
}
```

- `banner_height`: 24 to 160 pixels.
- `mode`: `cover` (default) fills the strip and crops the overflow, `stretch` squeezes the whole picture into it, `tile` repeats it at its natural proportions.
- `base`: which built-in theme to start from (`Classic mIRC`, `Night`, `Terminal`, `Ocean`, `Paper`); by default a dark picture starts from Night and a light one from Classic.
- `theme`: override single colours (`#rrggbb`). Names: `bg fg ts info warn error new clear self meta bot hist pane_bg pane_fg entry_bg entry_fg sel_bg sel_fg me_bg me_fg hl_bg hl_fg`.

Sharing a skin is copying its file or folder. Skins never run code. Pictures over 25 million pixels and files that cannot be read are ignored; a broken skin never stops mcIRC from starting.
Updates add or refresh the skins that ship with mcIRC and never delete yours.
