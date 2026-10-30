# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************

#load("@rules_pkg//pkg:mappings.bzl", "pkg_attributes", "pkg_files")
load("@score_itf//:defs.bzl", "py_itf_test")
#load("@score_rules_imagefs//rules/linux:ext4.bzl", "ext4")
#load("@score_rules_imagefs//rules/qnx:ifs.bzl", "qnx_ifs")

py_itf_test(
    name = "mytest",
    srcs = ["test_full_feature_qemu.py"],
    args = ["--docker-image=ubuntu:24.04"],
    plugins = ["@score_itf//score/itf/plugins:docker_plugin"]
)



# py_itf_test(
#     name = "test_full_feature_qemu",
#     srcs = ["test_full_feature_qemu.py"],
#     args = [
#         "--qemu-config=$(location //ubuntu_x86_64:qemu_config)",
#         "--qemu-rootfs=$(location //ubuntu_x86_64:image)",
#     ],
#     # data = [
#     #     "//path:qemu_image",
#     #     "qemu_config.json",
#     # ],
#     plugins = ["@score_itf//score/itf/plugins:qemu_plugin"],
# )
