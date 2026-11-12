# The open orb's instrument samples

`samples.bin` holds a few recorded notes of each instrument the open orb's Cornfield Chase arrangement plays (`rouh/static/app/orb_cornfield.js`), cut short, looped, mixed to one channel and compressed to MP3; `samples.json` says where each note is.
`tools/orb_cornfield/build_samples.py` makes both again from the source.

## Source and licence

All of them come from the **Versilian Community Sample Library, VSCO 2 Community Edition**, by Versilian Studios LLC, <https://github.com/sgossner/VSCO-2-CE>, at commit `440300901dfe9275fd84e0b7763af1f8443ae62e`.
It is released under **CC0 1.0 Universal** (public domain dedication): <https://creativecommons.org/publicdomain/zero/1.0/>.
Nothing is owed for using, changing or passing them on; the credit below is given because the library asks for it kindly.

| Instrument here | From the library | Credit |
|---|---|---|
| `organ` | Keys/Organ/Quiet, third manual | Organ sampled by Simon Dalzell of Ivy Audio, Winter 2015-16, redistributed by Versilian Studios LLC |
| `organ_full` | Keys/Organ/Loud, third manual open | the same |
| `pedal`, `pedal_full` | Keys/Organ, pedal quiet and loud | the same |
| `piano` | Keys/Upright Piano, dynamic 2 | Upright Piano sampled by Simon Dalzell of Ivy Audio, Winter 2015-16, redistributed by Versilian Studios LLC |
| `violins` | Strings/Violin Section/susVib | Versilian Studios LLC |
| `cellos` | Strings/Cello Section/susvib | Versilian Studios LLC |
| `basses` | Strings/Solo Contrabass/SusVib | Versilian Studios LLC |

## The music is a different matter

The samples are free.
The piece they play is not: "Cornfield Chase" is Hans Zimmer's, from Interstellar (2014), and belongs to its composer and publisher.
The arrangement is written out note by note in `orb_cornfield.js` and uses nothing from the soundtrack, but it is still an arrangement of somebody else's composition, so it sits behind the switch `orb_cornfield`, off on every installation, and must not ship on by default in a public release without the rights cleared.
