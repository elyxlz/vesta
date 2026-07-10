# CGO build environment for the whatsapp CLI: one owner, sourced by the
# launcher and by check.sh. WHISPER_CPP_DIR overrides the whisper install
# location (default /opt/whisper.cpp, where the agent image bakes it).
WHISPER_DIR="${WHISPER_CPP_DIR:-/opt/whisper.cpp}"
export CGO_ENABLED=1
export C_INCLUDE_PATH="$WHISPER_DIR/include:$WHISPER_DIR/ggml/include"
export LIBRARY_PATH="$WHISPER_DIR/build-static/src:$WHISPER_DIR/build-static/ggml/src"
export CGO_CFLAGS="-DSQLITE_ENABLE_FTS5"
export CGO_LDFLAGS="-lwhisper -lggml -lggml-base -lggml-cpu -lm -lstdc++ -fopenmp"
