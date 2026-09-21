# sgf2pdf -- .sgf -> .gnos -> .tex -> .pdf, one page per diagram,
# plus one combined PDF holding every page.
#
#   make             build every page PDF and the combined one
#   make -j8         ... in parallel
#   make diagrams    stop after the .gnos files
#   make sources     stop after the .tex files
#   make pdfs        just the one-page PDFs
#   make combined    just the combined PDF
#   make check       verify the gnos fonts are installed
#   make clean       remove everything generated
#
# Directories are overridable:  make SGFDIR=../mybook/sgf PDFDIR=out

SGFDIR   ?= sgf
GNOSDIR  ?= gnos
PAGESDIR ?= pages
PDFDIR   ?= pdf

# The combined document, written next to this Makefile.
ALLPDF   ?= all.pdf
ALLTEX   := $(ALLPDF:.pdf=.tex)

# Board font size in points. \gnosfontsize snaps to 8/9/10/11/12/14/16/20,
# and anything above 16 becomes 20 -- there is no smooth scaling.
SIZE     ?= 16

PYTHON   ?= python3
LATEX    ?= pdflatex

SGFS  := $(wildcard $(SGFDIR)/*.sgf)
GNOSS := $(patsubst $(SGFDIR)/%.sgf,$(GNOSDIR)/%.gnos,$(SGFS))
TEXS  := $(patsubst $(GNOSDIR)/%.gnos,$(PAGESDIR)/%.tex,$(GNOSS))
PDFS  := $(patsubst $(GNOSDIR)/%.gnos,$(PDFDIR)/%.pdf,$(GNOSS))

# Note: the convenience targets are named 'diagrams'/'sources'/'pdfs' rather
# than 'gnos'/'pages'/'pdf', which would collide with the directories.
.PHONY: all diagrams sources pdfs combined check clean
.DEFAULT_GOAL := all

all: pdfs combined

diagrams: $(GNOSS)
sources: $(TEXS)
pdfs: $(PDFS)
combined: $(ALLPDF)

# Fail early and legibly rather than letting pdflatex die on a missing font.
check:
	@kpsewhich gnos.sty >/dev/null 2>&1 || { \
	  echo "error: the gnos LaTeX fonts are not installed."; \
	  echo "  git clone https://github.com/otrego/go-type1"; \
	  echo "  go-type1/installer.sh install gnos"; \
	  exit 1; }

# Both scripts create their output directory, so there is no mkdir rule here.
$(GNOSDIR)/%.gnos: $(SGFDIR)/%.sgf sgf2gnos.py
	$(PYTHON) sgf2gnos.py $< -o $@

$(PAGESDIR)/%.tex: $(GNOSDIR)/%.gnos gnos2tex.py
	$(PYTHON) gnos2tex.py $< -o $@ --size $(SIZE)

# pdflatex runs inside $(PAGESDIR) so the .tex's relative path to its .gnos
# file resolves, and writes the PDF (plus its .aux/.log) into $(PDFDIR).
# TEXINPUTS points back here for sgf2pdf.sty -- $(CURDIR) rather than '..' so
# that the directories can live anywhere, including outside the project. The
# trailing ':' keeps the default search path in play.
#
# 'check' is an order-only prerequisite: it runs before the first page is
# typeset, including under make -j, but never marks a PDF out of date.
# On failure the .aux/.log are deliberately left behind for debugging.
$(PDFDIR)/%.pdf: $(PAGESDIR)/%.tex $(GNOSDIR)/%.gnos sgf2pdf.sty | check
	@mkdir -p $(PDFDIR)
	cd $(PAGESDIR) && TEXINPUTS=$(CURDIR):$$TEXINPUTS \
	  $(LATEX) -interaction=nonstopmode -halt-on-error \
	  -output-directory=$(abspath $(PDFDIR)) $*.tex >/dev/null
	@rm -f $(PDFDIR)/$*.aux $(PDFDIR)/$*.log

# The combined document is generated from the .gnos files directly rather than
# by concatenating the page PDFs: same template, same pages, but one pdflatex
# run and no dependency on an external PDF-merging tool.
$(ALLTEX): $(GNOSS) gnos2tex.py
	$(PYTHON) gnos2tex.py --all $@ --size $(SIZE) $(GNOSS)

# As with the page rule, pdflatex runs in the .tex file's own directory, so
# the relative paths to the .gnos files resolve and the PDF lands next to it
# -- which matters as soon as ALLPDF points somewhere other than here.
$(ALLPDF): $(ALLTEX) $(GNOSS) sgf2pdf.sty | check
	cd $(dir $(abspath $(ALLTEX))) && TEXINPUTS=$(CURDIR):$$TEXINPUTS \
	  $(LATEX) -interaction=nonstopmode -halt-on-error $(notdir $(ALLTEX)) >/dev/null
	@rm -f $(ALLTEX:.tex=.aux) $(ALLTEX:.tex=.log)

# Without this, make treats the .gnos and .tex files as intermediates and
# deletes them once the PDFs are built.
.PRECIOUS: $(GNOSDIR)/%.gnos $(PAGESDIR)/%.tex

clean:
	rm -f $(GNOSDIR)/*.gnos
	rm -f $(PAGESDIR)/*.tex
	rm -f $(PDFDIR)/*.pdf $(PDFDIR)/*.aux $(PDFDIR)/*.log
	rm -f $(ALLTEX) $(ALLPDF) $(ALLTEX:.tex=.aux) $(ALLTEX:.tex=.log)
