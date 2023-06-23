# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from os import environ

from . import QEM_DASHBOARD
from .errors import PostOpenQAError
from .loader.config import get_onearch, load_metadata
from .loader.qem import get_incidents
from .openqa import openQAInterface
from .utils import retry3 as requests

log = getLogger("bot.openqabot")


class OpenQABot:
    def __init__(self, args: Namespace) -> None:
        log.info("Bot schedule starts now")
        self.dry = args.dry
        self.ignore_onetime = args.ignore_onetime
        self.token = {"Authorization": f"Token {args.token}"}
        self.incidents = get_incidents(self.token)
        log.info(f"{len(self.incidents)} incidents loaded from qem dashboard")

        extrasettings = get_onearch(args.singlearch)

        self.workers = load_metadata(
            args.configs, args.disable_aggregates, args.disable_incidents, extrasettings
        )

        self.openqa = openQAInterface(args)
        self.ci = environ.get("CI_JOB_URL")

    def post_qem(self, data, api) -> None:
        if not self.openqa:
            log.warning(
                f"No valid openQA configuration specified: '{data}' not posted to dashboard"
            )
            return

        url = QEM_DASHBOARD + api
        try:
            res = requests.put(url, headers=self.token, json=data)
            log.info(
                f'Put to dashboard result {res.status_code}, database id: {res.json().get("id", "No id?")}'
            )
        except Exception as e:
            log.exception(e)
            raise e

    def post_openqa(self, data) -> None:
        self.openqa.post_job(data)

    def __call__(self):
        log.info("Starting bot mainloop")
        post = []
        for worker in self.workers:
            post += worker(self.incidents, self.token, self.ci, self.ignore_onetime)

        if self.dry:
            log.info(f"Would trigger {len(post)} products in openQA")
            for job in post:
                log.info(job)

        else:
            log.info(f"Triggering {len(post)} products in openQA")
            for job in post:
                log.info(f"Triggering {str(job)}")
                try:
                    self.post_openqa(job["openqa"])
                except PostOpenQAError:
                    log.info("POST failed, not updating dashboard")
                else:
                    self.post_qem(job["qem"], job["api"])

        log.info("End of bot run")

        return 0
