.PHONY: pdf preview check-preview clean

pdf:
	mkdir -p build
	tectonic --keep-logs --outdir build main.tex

preview: pdf
	python3 ../python/snapshot_paper.py

check-preview:
	python3 ../python/snapshot_paper.py --check

clean:
	python3 -c "from pathlib import Path; [p.unlink() for p in Path('build').glob('*') if p.is_file()]"
