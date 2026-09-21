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
# So are the typesetting settings:  make SIZE=12 NOTES=1

ifeq ($(filter 4.% 5.%,$(MAKE_VERSION)),)
$(error GNU Make 4+ required (macOS: brew install make, then use gmake))
endif

SGFDIR   ?= sgf
GNOSDIR  ?= gnos
PAGESDIR ?= pages
PDFDIR   ?= pdf

# The combined document, written next to this Makefile.
ALLPDF   ?= all.pdf
ALLTEX   := $(ALLPDF:.pdf=.tex)

# \gnosfontsize snaps to 8/9/10/11/12/14/16/20; anything above 16 becomes 20.
SIZE     ?= 16

# NOTES=1 prints each diagram's SGF comment, minus VSZ/CPT, under its caption.
NOTES    ?= 0
NOTESFLAG := $(if $(filter-out 0 n no off false,$(NOTES)),--notes,)

PYTHON   ?= python3
LATEX    ?= pdflatex

# Stamp file: make compares timestamps, not variable values.
CONFIG := $(PAGESDIR)/.build-config
CONFIGTEXT := SIZE=$(SIZE) NOTES=$(NOTESFLAG)

SGFS  := $(wildcard $(SGFDIR)/*.sgf)
GNOSS := $(patsubst $(SGFDIR)/%.sgf,$(GNOSDIR)/%.gnos,$(SGFS))
TEXS  := $(patsubst $(GNOSDIR)/%.gnos,$(PAGESDIR)/%.tex,$(GNOSS))
PDFS  := $(patsubst $(GNOSDIR)/%.gnos,$(PDFDIR)/%.pdf,$(GNOSS))

# Targets are diagrams/sources/pdfs; gnos/pages/pdf are the directories.
.PHONY: all diagrams sources pdfs combined check clean force
.DEFAULT_GOAL := all

all: pdfs combined

diagrams: $(GNOSS)
sources: $(TEXS)
pdfs: $(PDFS)
combined: $(ALLPDF)

check:
	@kpsewhich gnos.sty >/dev/null 2>&1 || { \
	  echo "error: the gnos LaTeX fonts are not installed."; \
	  echo "  git clone https://github.com/otrego/go-type1"; \
	  echo "  go-type1/installer.sh install gnos"; \
	  exit 1; }

# Both scripts create their own output directory.
$(GNOSDIR)/%.gnos: $(SGFDIR)/%.sgf sgf2gnos.py
	$(PYTHON) sgf2gnos.py $< -o $@

# On a settings change, delete the typeset output so it is rebuilt.
$(CONFIG): force
	@mkdir -p $(dir $@)
	@printf '%s\n' '$(CONFIGTEXT)' | cmp -s - $@ 2>/dev/null || { \
	  printf '%s\n' '$(CONFIGTEXT)' > $@; \
	  rm -f $(TEXS) $(ALLTEX) $(PDFS) $(ALLPDF); }

$(PAGESDIR)/%.tex: $(GNOSDIR)/%.gnos gnos2tex.py $(CONFIG)
	$(PYTHON) gnos2tex.py $< -o $@ --size $(SIZE) $(NOTESFLAG)

# Run in $(PAGESDIR) so the .tex's relative .gnos path resolves; TEXINPUTS
# finds sgf2pdf.sty. 'check' is order-only: it runs first, under -j too.
$(PDFDIR)/%.pdf: $(PAGESDIR)/%.tex $(GNOSDIR)/%.gnos sgf2pdf.sty | check
	@mkdir -p $(PDFDIR)
	cd $(PAGESDIR) && TEXINPUTS=$(CURDIR):$$TEXINPUTS \
	  $(LATEX) -interaction=nonstopmode -halt-on-error \
	  -output-directory=$(abspath $(PDFDIR)) $*.tex >/dev/null
	@rm -f $(PDFDIR)/$*.aux $(PDFDIR)/$*.log

# Built from the .gnos files, not by merging the page PDFs: no external tool.
$(ALLTEX): $(GNOSS) gnos2tex.py $(CONFIG)
	$(PYTHON) gnos2tex.py --all $@ --size $(SIZE) $(NOTESFLAG) $(GNOSS)

$(ALLPDF): $(ALLTEX) $(GNOSS) sgf2pdf.sty | check
	cd $(dir $(abspath $(ALLTEX))) && TEXINPUTS=$(CURDIR):$$TEXINPUTS \
	  $(LATEX) -interaction=nonstopmode -halt-on-error $(notdir $(ALLTEX)) >/dev/null
	@rm -f $(ALLTEX:.tex=.aux) $(ALLTEX:.tex=.log)

# Otherwise make treats the .gnos and .tex files as deletable intermediates.
.PRECIOUS: $(GNOSDIR)/%.gnos $(PAGESDIR)/%.tex

clean:
	rm -f $(GNOSDIR)/*.gnos
	rm -f $(PAGESDIR)/*.tex $(CONFIG)
	rm -f $(PDFDIR)/*.pdf $(PDFDIR)/*.aux $(PDFDIR)/*.log
	rm -f $(ALLTEX) $(ALLPDF) $(ALLTEX:.tex=.aux) $(ALLTEX:.tex=.log)
