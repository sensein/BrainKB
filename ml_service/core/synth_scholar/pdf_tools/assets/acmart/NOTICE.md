# Bundled ACM class (acmart)

`acmart.cls` v2.03 (2024/02/04), unmodified, with its source `acmart.dtx`/`acmart.ins` (the class's terms require the source to travel with it), from CTAN
(<https://ctan.org/pkg/acmart>), distributed under the LaTeX Project Public
License 1.3c (<https://www.latex-project.org/lppl/>). `README.acmart` is the
package's own README. Do not edit `acmart.cls`; the licence requires a modified
copy to be renamed.

It is the class behind the Overleaf "ACM Journals Primary Article Template"
(`\documentclass[acmsmall]{acmart}`). `generate_review_pdf.py --layout acm`
puts this directory on the TeX search path (`TEXINPUTS`; `-Z search-path` for
tectonic), so the layout works offline and does not depend on the installed
TeX distribution's copy or on tectonic downloading one.

The class still loads standard packages (libertine, newtxmath, totpages,
environ, hyperxmp, comment, ncctools, …), which any TeX Live / MacTeX install
provides and tectonic fetches once into its cache. Update by copying a newer
`acmart.cls` from CTAN and changing the version above.
