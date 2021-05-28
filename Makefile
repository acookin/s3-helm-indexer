IMAGE_NAME := s3-helm-indexer
TAG ?= $(shell git rev-parse --short HEAD)

build:
	@docker build -t $(IMAGE_NAME):$(TAG) .
.PHONY: build

publish: build
	@[ -n "$(REGISTRY)" ] || (echo "REGISTRY must be set to push"; exit 1)
	@docker tag $(IMAGE_NAME):$(TAG) $(REGISTRY)/$(IMAGE_NAME):$(TAG)
	@docker push $(REGISTRY)/$(IMAGE_NAME):$(TAG)
.PHONY: publish

set-image: publish
	@echo "Setting image to $(REGISTRY)/$(IMAGE_NAME):$(TAG)"
	@(cd kustomize/base && kustomize edit set image helm-indexer=$(REGISTRY)/$(IMAGE_NAME):$(TAG))
.PHONY: set-image

deploy:
	@[ -n "$(DEPLOY_PATCH)" ] || (echo "Must set DEPLOY_PATCH to specify which kustomize patch you want to deploy"; exit 1)
	@kustomize build ./kustomize/patch/$(DEPLOY_PATCH) | kubectl apply -f -
.PHONY: deploy
