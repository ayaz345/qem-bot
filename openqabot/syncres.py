# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Dict

from .loader.qem import post_job
from .openqa import openQAInterface
from .types import Data
from .utils import normalize_results

log = getLogger("bot.syncres")


class SyncRes:
    operation = "null"

    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)

    @classmethod
    def normalize_data(cls, data: Data, job):
        ret = {
            "job_id": job["id"],
            "incident_settings": data.settings_id
            if cls.operation == "incident"
            else None,
            "update_settings": data.settings_id
            if cls.operation == "aggregate"
            else None,
            "name": job["name"],
            "distri": data.distri,
            "group_id": job["group_id"],
            "job_group": job["group"],
            "version": data.version,
            "arch": data.arch,
            "flavor": data.flavor,
            "status": normalize_results(job["result"]),
        }
        ret["build"] = data.build

        return ret

    def _is_in_devel_group(self, data: Data) -> bool:
        return (
            "Devel" in data["group"]
            or "Test" in data["group"]
            or self.client.is_devel_group(data["group_id"])
        )

    def filter_jobs(self, data) -> bool:
        """Filter out invalid/development jobs from results"""

        if "group" not in data:
            return False

        if data["clone_id"]:
            log.info(f"""Job '{data["clone_id"]}' already has a clone, ignoring""")
            return False

        if self._is_in_devel_group(data):
            log.info(
                f"""Ignoring job '{data["id"]}' in development group '{data["group"]}'"""
            )
            return False

        return True

    def post_result(self, result):
        log.debug(
            f'Posting results of {self.operation} job {result["job_id"]} with status {result["status"]}'
        )
        log.debug(f"Full post data: {pformat(result)}")

        if not self.dry and self.client:
            post_job(self.token, result)
        else:
            log.info("Dry run -- data in dashboard untouched")
