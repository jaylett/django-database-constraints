.PHONY: check coverage

check:
	python runtests.py

coverage:
	coverage run --parallel --branch --source='.' runtests.py postgresql
	coverage run --append --parallel --branch --source='.' runtests.py mysql
	coverage combine
	coverage html --omit=setup.py
