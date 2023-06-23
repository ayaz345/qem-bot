# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from logging import getLogger
from pathlib import Path
from typing import List, Set, Union

from ruamel.yaml import YAML  # type: ignore

from ..errors import NoTestIssues
from ..types import Data
from ..types.aggregate import Aggregate
from ..types.incidents import Incidents

log = getLogger("bot.loader.config")


def load_metadata(
    path: Path, aggregate: bool, incidents: bool, extrasettings: Set[str]
) -> List[Union[Aggregate, Incidents]]:
    ret: List[Union[Aggregate, Incidents]] = []

    loader = YAML(typ="safe")

    for p in path.glob("*.yml"):
        try:
            data = loader.load(p)
        except Exception as e:
            log.exception(e)
            continue

        try:
            settings = data.get("settings")
        except AttributeError:
            # not valid yaml for bot settings
            continue

        if "product" not in data:
            log.debug(f"Skipping invalid config {p}")
            continue

        if settings:
            for key in data:
                if key == "incidents" and not incidents:
                    ret.append(
                        Incidents(data["product"], settings, data[key], extrasettings)
                    )
                elif key == "aggregate" and not aggregate:
                    try:
                        ret.append(Aggregate(data["product"], settings, data[key]))
                    except NoTestIssues:
                        log.warning(f"""No 'test_issues' in {data["product"]} config""")
                else:
                    continue
    return ret


def read_products(path: Path) -> List[Data]:
    loader = YAML(typ="safe")
    ret = []

    for p in path.glob("*.yml"):
        data = loader.load(p)

        if not data:
            log.info(f"Skipping invalid config {str(p)} - empty config")
            continue
        if not isinstance(data, dict):
            log.info(f"Skipping invalid config {str(p)} - invalid format")
            continue

        try:
            flavor = data["aggregate"]["FLAVOR"]
        except KeyError:
            log.info(f"Config {str(p)} does not have aggregate")
            continue

        try:
            distri = data["settings"]["DISTRI"]
            version = data["settings"]["VERSION"]
            product = data["product"]
        except Exception as e:
            log.exception(e)
            continue

        ret.extend(
            Data(0, 0, flavor, arch, distri, version, "", product)
            for arch in data["aggregate"]["archs"]
        )
    return ret


def get_onearch(path: Path) -> Set[str]:
    loader = YAML(typ="safe")

    try:
        data = loader.load(path)
    except Exception as e:
        log.exception(e)
        return set()

    return set(data)
