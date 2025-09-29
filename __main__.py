import pulumi
from pulumi import ResourceOptions, Config
from pulumi_kubernetes.core.v1 import Namespace
from pulumi_kubernetes.helm.v3 import Release

cfg = Config("airbyte")

# Stack-configured knobs (with sensible defaults for local dev)
ns_name        = cfg.get("namespace")
repo_url       = cfg.get("repoUrl")
chart_name     = cfg.get("chart")
chart_version  = cfg.get("chartVersion")
app_image_tag  = cfg.get("appImageTag")
airbyte_url    = cfg.get("airbyteUrl")

# Create / ensure namespace
ns = Namespace(
    "airbyte-namespace",
    metadata={"name": ns_name},
)

# Build values to pass to the Helm release. Keep it minimal and stack-driven.
values = {
    "global": {
        "airbyteUrl": airbyte_url,
        "image": {
            # Most Airbyte components inherit this image tag
            "tag": app_image_tag,
        },
    },
}

# Create the Helm release (server-side chart fetch)
airbyte = Release(
    "airbyte",
    namespace=ns.metadata["name"],
    chart=chart_name,
    version=chart_version,  # pin chart version for reproducibility
    repository_opts={"repo": repo_url},
    values=values,
    opts=ResourceOptions(depends_on=[ns]),
)

# Handy stack outputs
pulumi.export("namespace", ns.metadata["name"])
pulumi.export("helmReleaseName", airbyte.name)
pulumi.export("airbyteUrl", airbyte_url)
