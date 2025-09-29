import pulumi
from pulumi import ResourceOptions, Config
from pulumi_kubernetes.core.v1 import (
    Namespace,
    Secret,
    Service,
    PersistentVolumeClaim,
    ConfigMap
)
from pulumi_kubernetes.apps.v1 import StatefulSet
from pulumi_kubernetes.helm.v3 import Release

cfg = Config("airbyte")

# Stack-configured knobs (with sensible defaults for local dev)
ns_name        = cfg.get("namespace")
repo_url       = cfg.get("repoUrl")
chart_name     = cfg.get("chart")
chart_version  = cfg.get("chartVersion")
app_image_tag  = cfg.get("appImageTag")
airbyte_url    = cfg.get("airbyteUrl")

# Database configuration
db_name = "db-airbyte"
db_username = "airbyte_user"
db_password = "airbyte_password123"

# Create / ensure namespace
ns = Namespace(
    "airbyte-namespace",
    metadata={"name": ns_name},
)

# Create PostgreSQL ConfigMap for initialization
postgres_config = ConfigMap(
    "postgres-config",
    metadata={
        "name": "postgres-config",
        "namespace": ns.metadata["name"],
    },
    data={
        "POSTGRES_DB": db_name,
        "POSTGRES_USER": db_username,
        "POSTGRES_PASSWORD": db_password,
        "PGDATA": "/var/lib/postgresql/data/pgdata",
    },
    opts=ResourceOptions(depends_on=[ns]),
)

# Create PersistentVolumeClaim for PostgreSQL data
postgres_pvc = PersistentVolumeClaim(
    "postgres-pvc",
    metadata={
        "name": "postgres-pvc",
        "namespace": ns.metadata["name"],
    },
    spec={
        "accessModes": ["ReadWriteOnce"],
        "resources": {
            "requests": {
                "storage": "10Gi"
            }
        }
    },
    opts=ResourceOptions(depends_on=[ns]),
)

# Create PostgreSQL StatefulSet
postgres_statefulset = StatefulSet(
    "postgres",
    metadata={
        "name": "postgres",
        "namespace": ns.metadata["name"],
    },
    spec={
        "serviceName": "airbyte-db-svc",  # Changed to match expected service name
        "replicas": 1,
        "selector": {
            "matchLabels": {
                "app": "postgres"
            }
        },
        "template": {
            "metadata": {
                "labels": {
                    "app": "postgres"
                }
            },
            "spec": {
                "containers": [{
                    "name": "postgres",
                    "image": "postgres:13",
                    "ports": [{
                        "containerPort": 5432,
                        "name": "postgres"
                    }],
                    "envFrom": [{
                        "configMapRef": {
                            "name": "postgres-config"
                        }
                    }],
                    "volumeMounts": [{
                        "name": "postgres-storage",
                        "mountPath": "/var/lib/postgresql/data"
                    }],
                    "livenessProbe": {
                        "exec": {
                            "command": [
                                "pg_isready",
                                "-U", db_username,
                                "-d", db_name
                            ]
                        },
                        "initialDelaySeconds": 30,
                        "periodSeconds": 10,
                        "timeoutSeconds": 5,
                        "successThreshold": 1,
                        "failureThreshold": 3
                    },
                    "readinessProbe": {
                        "exec": {
                            "command": [
                                "pg_isready",
                                "-U", db_username,
                                "-d", db_name
                            ]
                        },
                        "initialDelaySeconds": 5,
                        "periodSeconds": 10,
                        "timeoutSeconds": 1,
                        "successThreshold": 1,
                        "failureThreshold": 3
                    }
                }],
                "volumes": [{
                    "name": "postgres-storage",
                    "persistentVolumeClaim": {
                        "claimName": "postgres-pvc"
                    }
                }]
            }
        }
    },
    opts=ResourceOptions(depends_on=[ns, postgres_config, postgres_pvc]),
)

# Create PostgreSQL Service with the name Airbyte expects
postgres_service = Service(
    "airbyte-db-svc",
    metadata={
        "name": "airbyte-db-svc",  # Changed to match expected service name
        "namespace": ns.metadata["name"],
    },
    spec={
        "selector": {
            "app": "postgres"
        },
        "ports": [{
            "port": 5432,
            "targetPort": 5432,
            "protocol": "TCP"
        }],
        "type": "ClusterIP"
    },
    opts=ResourceOptions(depends_on=[ns, postgres_statefulset]),
)

# Create Kubernetes secret for database credentials
db_secret = Secret(
    "airbyte-db-secret",
    metadata={
        "name": "airbyte-db-secret",
        "namespace": ns.metadata["name"],
    },
    string_data={
        "DATABASE_USER": db_username,
        "DATABASE_PASSWORD": db_password,
        "DATABASE_URL": f"jdbc:postgresql://airbyte-db-svc.{ns_name}.svc.cluster.local:5432/{db_name}",
        "database-user": db_username,  # Keep both formats for compatibility
        "database-password": db_password,
        "database-url": f"jdbc:postgresql://airbyte-db-svc.{ns_name}.svc.cluster.local:5432/{db_name}",
    },
    opts=ResourceOptions(depends_on=[ns, postgres_service]),
)

# Build values to pass to the Helm release with database configuration
values = {
    "global": {
        "airbyteUrl": airbyte_url,
        "image": {
            "tag": app_image_tag,
        },
        "database": {
            "secretName": "airbyte-db-secret",
            "secretValue": "database-url",
            "type": "external",
        },
        "jobs": {
            "database": {
                "secretName": "airbyte-db-secret",
                "secretValue": "database-url",
                "type": "external",
            }
        }
    },
    "postgresql": {
        "enabled": False,
    },
    "externalDatabase": {
        "host": f"airbyte-db-svc.{ns_name}.svc.cluster.local",  # Updated to match service name
        "port": 5432,
        "database": db_name,
        "user": db_username,
        "existingSecret": "airbyte-db-secret",
        "existingSecretPasswordKey": "database-password",
    }
}

# Create the Helm release (server-side chart fetch)
airbyte = Release(
    "airbyte",
    namespace=ns.metadata["name"],
    chart=chart_name,
    version=chart_version,
    repository_opts={"repo": repo_url},
    values=values,
    timeout=1800,
    opts=ResourceOptions(depends_on=[ns, db_secret, postgres_service]),  # Add postgres_service dependency
)

# Handy stack outputs
pulumi.export("namespace", ns.metadata["name"])
pulumi.export("helmReleaseName", airbyte.name)
pulumi.export("airbyteUrl", airbyte_url)
pulumi.export("databaseEndpoint", f"airbyte-db-svc.{ns_name}.svc.cluster.local:5432")
pulumi.export("databaseName", db_name)