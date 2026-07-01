SHELL := /bin/bash

NAMESPACE = svc0041t-wordpress
WP_CONTROLLER_IMAGE_NAME = quay-its.epfl.ch/svc0041/wp-controller
WP_CONTROLLER_IMAGE_TAG ?= latest

.PHONY: help
## Print this help
help:
	@echo "$$(tput setaf 2)Available rules:$$(tput sgr0)";sed -ne"/^## /{h;s/.*//;:d" -e"H;n;s/^## /---/;td" -e"s/:.*//;G;s/\\n## /===/;s/\\n//g;p;}" ${MAKEFILE_LIST}|awk -F === -v n=$$(tput cols) -v i=4 -v a="$$(tput setaf 6)" -v z="$$(tput sgr0)" '{printf"- %s%s%s\n",a,$$1,z;m=split($$2,w,"---");l=n-i;for(j=1;j<=m;j++){l-=length(w[j])+1;if(l<= 0){l=n-i-length(w[j])-1;}printf"%*s%s\n",-i," ",w[j];}}'

.PHONY: controller
## Launch wp-controller locally, against whatever cluster $KUBECONFIG points to
controller:
	WATCH_NAMESPACE=$(NAMESPACE) python3 main.py

.PHONY: dev
## Build and run wp-controller in Docker, against $KUBECONFIG (see docker-compose.dev.yml)
dev:
	docker compose -f docker-compose.dev.yml up --build

.PHONY: test
## Run the unit test suite
test:
	pytest

.PHONY: image
## Build, tag and push the image
image: build push

.PHONY: deploy
## Deploy wp-controller using the manifests in ./manifests
deploy:
	kubectl apply -f manifests/

.PHONY: delete
## Delete wp-controller using the manifests in ./manifests
delete:
	kubectl delete -f manifests/

.PHONY: build
## Build the image as `WP_CONTROLLER_IMAGE_NAME`
build:
	docker build -t $(WP_CONTROLLER_IMAGE_NAME):$(WP_CONTROLLER_IMAGE_TAG) .

.PHONY: push
## Push the image using `WP_CONTROLLER_IMAGE_TAG`
push:
	docker push $(WP_CONTROLLER_IMAGE_NAME):$(WP_CONTROLLER_IMAGE_TAG)
