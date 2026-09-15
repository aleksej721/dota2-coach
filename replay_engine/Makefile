CXX ?= clang++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic
CPPFLAGS ?= -Iinclude
BUILD_DIR := build
ENGINE := $(BUILD_DIR)/dota2-replay-engine
TESTS := $(BUILD_DIR)/test-engine

.PHONY: all clean sanitize test

all: $(ENGINE)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(ENGINE): src/engine.cpp src/main.cpp include/dota2replay/engine.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/engine.cpp src/main.cpp -o $@

$(TESTS): src/engine.cpp tests/test_engine.cpp include/dota2replay/engine.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/engine.cpp tests/test_engine.cpp -o $@

test: $(TESTS)
	$(TESTS)

sanitize: | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) -O1 -g -std=c++17 -Wall -Wextra -Wpedantic \
		-fsanitize=address,undefined -fno-omit-frame-pointer \
		src/engine.cpp tests/test_engine.cpp -o $(BUILD_DIR)/test-engine-sanitize
	$(BUILD_DIR)/test-engine-sanitize

clean:
	rm -rf $(BUILD_DIR)
