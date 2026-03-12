from __future__ import annotations


_GENERATED_PROTOBUF_SUFFIXES = (
    ".pb.h",
    ".pb.hh",
    ".pb.hpp",
    ".pb.cc",
    ".pb.cpp",
    ".pb.cxx",
)


def normalize_repo_rel_path(path_text: str) -> str:
    return path_text.replace("\\", "/").lstrip("./")


def is_generated_code_path(path_text: str) -> bool:
    rel_path = normalize_repo_rel_path(path_text).lower()
    file_name = rel_path.rsplit("/", 1)[-1]
    return file_name.endswith(_GENERATED_PROTOBUF_SUFFIXES)


def generated_code_globs() -> list[str]:
    return [f"*{suffix}" for suffix in _GENERATED_PROTOBUF_SUFFIXES]
