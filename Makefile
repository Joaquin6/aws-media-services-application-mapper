.PHONY: help init clean test validate mock create delete info deploy
.DEFAULT_GOAL := help

DIR = $(PWD)
PYTHON_VERSION = 3.6.8
LANG = en_US.UTF-8
LANGUAGE = en_US.UTF-8
LC_ALL = en_US.UTF-8
# Since we rely on paths relative to the makefile location, abort if@$(MAKE) isn't being run from there.
$(if $(findstring /,$(MAKEFILE_LIST)),$(error Please only invoke this makefile from the directory it resides in))

environment = "msam"
AWS_PROFILE ?= "msam-release"
AWS_S3BUCKET ?= "rodeolabz"

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

api-build: ## build the API. 	Ex. `make api-build AWS_S3BUCKET=your-bucket-name AWS_PROFILE=your-aws-profile`
	@chmod +x $(DIR)/api/*.sh
	$(DIR)/api/build.sh -b $(AWS_S3BUCKET) -p $(AWS_PROFILE)

init: ## Initialize the virtual environment. 	Make sure to run `pip install pipenv`
	@pipenv install --python $(PYTHON_VERSION) --dev

clean: ## clean and removes the existing virtualenv
	@pipenv --rm

create: test merge-lambda ## create env. 	Make sure to run `pip install sceptre`
	@sceptre launch $(environment)

delete: ## delete env. 	Make sure to run `pip install sceptre`
	@sceptre delete $(environment)

deploy: delete create ## delete and create

api-tests: ## run the unit tests
	@pip --no-cache-dir install -r api/msam/requirements.txt
	@pipenv run pytest -v -s api/events

tests: api-tests ## run the unit tests

merge-lambda: ## merge lambda in api gateway. 	Make sure to run `pip install aws-cfn-update`
	aws-cfn-update \
		lambda-inline-code \
		--resource Collector \
		--file api/events/lambda_function.py \
		api/events/MSAMEventCollector.yml
