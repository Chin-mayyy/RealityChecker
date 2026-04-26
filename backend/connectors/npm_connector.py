import requests  # pyright: ignore[reportMissingModuleSource]


def get_npm_package_data(package_name: str) -> dict:
    url = f"https://registry.npmjs.org/{package_name}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    latest_version = data.get("dist-tags", {}).get("latest")
    last_published = None
    if latest_version:
        last_published = data.get("time", {}).get(latest_version)
    return {
        "package": package_name,
        "latest_version": latest_version,
        "last_published": last_published,
    }


def get_pypi_package_data(package_name: str) -> dict:
    url = f"https://pypi.org/pypi/{package_name}/json"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    return {
        "package": package_name,
        "latest_version": data["info"]["version"],
    }
