#!/usr/bin/env python3
#
# Copyright (C) 2019-2021 Hiroshi Miura <miurahr@linux.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
import os
from typing import List


class AqtException(Exception):
    def __init__(self, *args, **kwargs):
        self.suggested_action: List[str] = kwargs.pop("suggested_action", [])
        self.should_show_help: bool = kwargs.pop("should_show_help", False)
        super(AqtException, self).__init__(*args, **kwargs)

    def __format__(self, format_spec) -> str:
        base_msg = "{}".format(super(AqtException, self).__format__(format_spec))
        if not self.suggested_action:
            return base_msg
        return f"{base_msg}\n{self._format_suggested_follow_up()}"

    def _format_suggested_follow_up(self) -> str:
        return ("=" * 30 + "Suggested follow-up:" + "=" * 30 + "\n") + "\n".join(
            ["* " + suggestion for suggestion in self.suggested_action]
        )


class ArchiveDownloadError(AqtException):
    pass


class ArchiveChecksumError(ArchiveDownloadError):
    pass


class ArchiveConnectionError(AqtException):
    pass


class ArchiveListError(AqtException):
    pass


class NoPackageFound(AqtException):
    pass


class EmptyMetadata(AqtException):
    pass


class CliInputError(AqtException):
    pass


class CliKeyboardInterrupt(AqtException):
    pass


class ArchiveExtractionError(AqtException):
    def __init__(self, extraction_tool: str, archive_failed_to_extract: str, *args, **kwargs):
        msg = f"`{extraction_tool}` failed to extract `{archive_failed_to_extract}`: {args[0]}"
        kwargs["suggested_action"] = (kwargs.get("suggested_action") or []) + [
            "Consider using another 7z extraction tool with `--external`\n"
            "  (see https://aqtinstall.readthedocs.io/en/latest/cli.html#cmdoption-list-tool-external)",
            "If this error persists, file a bug report at https://github.com/miurahr/aqtinstall/issues,\n"
            f"  and include the relevant log file at {os.getcwd()}/aqtinstall.log",
        ]
        super(ArchiveExtractionError, self).__init__(msg, *args[1:], **kwargs)


class UpdaterError(AqtException):
    pass
