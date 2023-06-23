# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from functools import lru_cache
from logging import getLogger
from typing import List
from urllib.error import HTTPError

import osc.conf
import osc.core
import re

from openqa_client.exceptions import RequestError
from openqabot.errors import NoResultsError
from openqabot.openqa import openQAInterface

from . import OBS_GROUP, OBS_MAINT_PRJ, OBS_URL, QEM_DASHBOARD
from .loader.qem import (
    IncReq,
    JobAggr,
    get_aggregate_settings,
    get_incident_settings,
    get_incidents_approver,
    get_single_incident,
)
from .utils import retry3 as requests

log = getLogger("bot.approver")


def _mi2str(inc: IncReq) -> str:
    return f"{OBS_MAINT_PRJ}:{str(inc.inc)}:{str(inc.req)}"


def _handle_http_error(e: HTTPError, inc: IncReq) -> bool:
    if e.code == 403:
        log.info(
            f"Received '{e.reason}'. Request {inc.req} likely already approved, ignoring"
        )
        return True
    elif e.code == 404:
        log.info(
            f"Received '{e.reason}'. Request {inc.req} removed or problem on OBS side, ignoring"
        )
        return False
    else:
        log.error(
            f"Received error {e.code}, reason: '{e.reason}' for Request {inc.req} - problem on OBS side"
        )
        return False


class Approver:
    def __init__(self, args: Namespace) -> None:
        self.dry = args.dry
        self.single_incident = args.incident
        self.token = {"Authorization": f"Token {args.token}"}
        self.all_incidents = args.all_incidents
        self.client = openQAInterface(args)

    def __call__(self) -> int:
        log.info("Start approving incidents in IBS")
        increqs = (
            get_single_incident(self.token, self.single_incident)
            if self.single_incident
            else get_incidents_approver(self.token)
        )

        overall_result = True
        incidents_to_approve = [inc for inc in increqs if self._approvable(inc)]

        log.info("Incidents to approve:")
        for inc in incidents_to_approve:
            log.info(f"* {_mi2str(inc)}")

        if not self.dry:
            osc.conf.get_config(override_apiurl=OBS_URL)
            for inc in incidents_to_approve:
                overall_result &= self.osc_approve(inc)

        log.info("End of bot run")

        return 0 if overall_result else 1

    def _approvable(self, inc: IncReq) -> bool:
        try:
            i_jobs = get_incident_settings(inc.inc, self.token, self.all_incidents)
        except NoResultsError as e:
            log.info(e)
            return False
        try:
            u_jobs = get_aggregate_settings(inc.inc, self.token)
        except NoResultsError as e:
            log.info(e)

            if any(i.withAggregate for i in i_jobs):
                log.info(f"Aggregate missing for {_mi2str(inc)}")
                return False

            u_jobs = []

        if not self.get_incident_result(i_jobs, "api/jobs/incident/", inc.inc):
            log.info(f"{_mi2str(inc)} has at least one failed job in incident tests")
            return False

        if any(i.withAggregate for i in i_jobs):
            if not self.get_incident_result(u_jobs, "api/jobs/update/", inc.inc):
                log.info(f"{_mi2str(inc)} has at least one failed job in aggregate tests")
                return False

        # everything is green --> add incident to approve list
        return True

    @lru_cache(maxsize=512)
    def is_job_marked_acceptable_for_incident(self, job_id: int, inc: int) -> bool:
        regex = re.compile(r"\@review\:acceptable_for\:incident_%s\:(.+)" % inc)
        try:
            for comment in self.client.get_job_comments(job_id):
                if regex.match(comment["text"]):
                    return True
        except RequestError:
            pass
        return False

    @lru_cache(maxsize=128)
    def get_jobs(self, job_aggr: JobAggr, api: str, inc: int) -> bool:
        results = requests.get(
            QEM_DASHBOARD + api + str(job_aggr.id), headers=self.token
        ).json()

        # keep jobs explicitly marked as acceptable for this incident by openQA comments
        for res in results:
            ok_job = res["status"] == "passed"
            if ok_job:
                continue
            if self.is_job_marked_acceptable_for_incident(res["job_id"], inc):
                log.info(
                    f'Ignoring failed job {str(self.client.url.geturl())}/t{res["job_id"]} for incident {inc} due to openQA comment'
                )
                res["status"] = "passed"
            else:
                log.info(
                    f'Found failed, not-ignored job {str(self.client.url.geturl())}/t{res["job_id"]} for incident {inc}'
                )
                break

        if not results:
            raise NoResultsError(
                f"Job setting {str(job_aggr.id)} not found for incident {inc}"
            )

        return all(r["status"] == "passed" for r in results)

    def get_incident_result(self, jobs: List[JobAggr], api: str, inc: int) -> bool:
        res = False

        for job_aggr in jobs:
            try:
                res = self.get_jobs(job_aggr, api, inc)
            except NoResultsError as e:
                log.info(e)
                continue
            if not res:
                return False

        return res

    @staticmethod
    def osc_approve(inc: IncReq) -> bool:
        msg = f"Request accepted for '{OBS_GROUP}' based on data in {QEM_DASHBOARD}"
        log.info(
            (
                "Accepting review for "
                + OBS_MAINT_PRJ
                + f":{str(inc.inc)}:{str(inc.req)}"
            )
        )

        try:
            osc.core.change_review_state(
                apiurl=OBS_URL,
                reqid=str(inc.req),
                newstate="accepted",
                by_group=OBS_GROUP,
                message=msg,
            )
        except HTTPError as e:
            return _handle_http_error(e, inc)
        except Exception as e:
            log.exception(e)
            return False

        return True
