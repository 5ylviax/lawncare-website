.DEFAULT_GOAL := build

BINARY := bin/lawncare$(shell go env GOEXE)

.PHONY: fmt vet lint test build run clean

fmt:
	go fmt ./...

vet: fmt
	go vet ./...

# Install with:
# go install honnef.co/go/tools/cmd/staticcheck@latest
lint: fmt
	staticcheck ./...

test: vet
	go test ./...

build: vet
	go build -o "$(BINARY)" ./cmd

run: build
	"$(BINARY)"

clean:
	go clean
ifeq ($(OS),Windows_NT)
	if exist bin rmdir /s /q bin
else
	rm -rf bin
endif