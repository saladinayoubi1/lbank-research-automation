from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus-build-verification.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_android_release_evidence_uses_observed_toolchain_with_fixed_policy() -> None:
    text = _workflow_text()

    assert "Verify and capture Android toolchain" in text
    assert "java -XshowSettings:properties -version" in text
    assert "gradle --version" in text
    assert 'NEXUS_RELEASE_JAVA=$java_version' in text
    assert 'NEXUS_RELEASE_GRADLE=$gradle_version' in text
    assert '--build-parameter "java=$NEXUS_RELEASE_JAVA"' in text
    assert '--build-parameter "gradle=$NEXUS_RELEASE_GRADLE"' in text
    assert "--expected-build-parameter 'java=17'" in text
    assert "--expected-build-parameter 'gradle=8.9'" in text
    assert "--build-parameter 'java=17'" not in text
    assert "--build-parameter 'gradle=8.9'" not in text


def test_windows_release_evidence_uses_observed_runtime_package_and_signing_state() -> None:
    text = _workflow_text()

    assert "Verify and capture Windows build identity" in text
    assert "sys.version_info.major" in text
    assert "node --version" in text
    assert "require('./desktop/nexus-product/package.json').version" in text
    assert "CSC_IDENTITY_AUTO_DISCOVERY: 'false'" in text
    assert "Get-AuthenticodeSignature" in text
    assert "Status.ToString() -ne 'NotSigned'" in text
    assert "NEXUS_RELEASE_CODE_SIGNING=disabled" in text
    assert '--build-parameter "product_version=$env:NEXUS_RELEASE_PRODUCT_VERSION"' in text
    assert '--build-parameter "python=$env:NEXUS_RELEASE_PYTHON"' in text
    assert '--build-parameter "node=$env:NEXUS_RELEASE_NODE"' in text
    assert '--build-parameter "code_signing=$env:NEXUS_RELEASE_CODE_SIGNING"' in text
    assert "--expected-build-parameter 'product_version=5.1.0'" in text
    assert "--expected-build-parameter 'python=3.12'" in text
    assert "--expected-build-parameter 'node=22'" in text
    assert "--expected-build-parameter 'code_signing=disabled'" in text
    assert "--build-parameter 'product_version=5.1.0'" not in text
    assert "--build-parameter 'python=3.12'" not in text
    assert "--build-parameter 'node=22'" not in text
    assert "--build-parameter 'code_signing=disabled'" not in text
