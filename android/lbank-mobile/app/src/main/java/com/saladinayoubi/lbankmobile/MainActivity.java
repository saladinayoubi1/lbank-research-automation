package com.saladinayoubi1.lbankmobile;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.os.Bundle;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.net.URL;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;

public final class MainActivity extends Activity {
    private static final String KEY_ALIAS = "nexus_gateway_token";
    private static final String GATEWAY_SECRET_ID = "gateway";
    private static final int MAX_RESPONSE_BYTES = 1_000_000;
    private static final int MAX_REQUEST_CHARS = 4096;
    private static final String BYBIT_BASE_URL = "https://api.bybit.com";
    private static final Set<String> PUBLIC_INTERVALS = new HashSet<>(Arrays.asList("15", "60", "240"));
    private static final Set<String> ALLOWED_PATHS = new HashSet<>(Arrays.asList(
            "/health",
            "/api/readiness/summary",
            "/api/readiness/series",
            "/api/mission-control",
            "/api/integrations/zotero",
            "/api/integrations/research"
    ));
    private static final Set<String> SERIES_QUERY_KEYS = new HashSet<>(Arrays.asList(
            "symbol", "timeframe", "limit", "offset"
    ));

    private WebView webView;
    private final ExecutorService executor = Executors.newFixedThreadPool(3);

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        webView.addJavascriptInterface(new NativeGateway(), "NexusNative");
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        webView.loadUrl("file:///android_asset/index.html");
    }

    private SecretKey getOrCreateKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY_ALIAS)) {
            return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null)).getSecretKey();
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return generator.generateKey();
    }

    private String encrypt(String plain) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] iv = cipher.getIV();
        byte[] encrypted = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
        return Base64.encodeToString(iv, Base64.NO_WRAP) + "." + Base64.encodeToString(encrypted, Base64.NO_WRAP);
    }

    private String decrypt(String packed) throws Exception {
        if (packed == null || !packed.contains(".")) return "";
        String[] parts = packed.split("\\.", 2);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    private void assertGatewaySecretId(String id) {
        if (!GATEWAY_SECRET_ID.equals(id)) {
            throw new SecurityException("Only the NEXUS gateway token is accepted by the native bridge");
        }
    }

    private URL gatewayBaseUrl() throws Exception {
        URL base = new URL(BuildConfig.NEXUS_GATEWAY_URL);
        if (!"https".equalsIgnoreCase(base.getProtocol())) {
            throw new SecurityException("Android NEXUS gateway must use HTTPS");
        }
        if (base.getUserInfo() != null || base.getQuery() != null || base.getRef() != null || !(base.getPath().isEmpty() || "/".equals(base.getPath()))) {
            throw new SecurityException("Android NEXUS gateway configuration must be an origin only");
        }
        return base;
    }

    private String validateRelativePath(String requestJson) throws Exception {
        if (requestJson == null || requestJson.length() > MAX_REQUEST_CHARS) {
            throw new SecurityException("Gateway request is malformed or oversized");
        }
        JSONObject request = new JSONObject(requestJson);
        Iterator<String> keys = request.keys();
        if (!keys.hasNext()) throw new SecurityException("Gateway request is empty");
        String onlyKey = keys.next();
        if (!"path".equals(onlyKey) || keys.hasNext()) {
            throw new SecurityException("Only a bounded gateway path is accepted");
        }
        String rawPath = request.getString("path");
        if (rawPath.length() > MAX_REQUEST_CHARS || rawPath.contains("#") || rawPath.startsWith("//")) {
            throw new SecurityException("Gateway path is invalid");
        }
        URI relative = new URI(rawPath);
        if (relative.isAbsolute() || relative.getHost() != null || relative.getUserInfo() != null) {
            throw new SecurityException("Absolute URLs are forbidden in WebView requests");
        }
        String path = relative.getPath();
        if (!ALLOWED_PATHS.contains(path)) {
            throw new SecurityException("Gateway route is not allowlisted");
        }
        String rawQuery = relative.getRawQuery();
        if (rawQuery != null && !rawQuery.isEmpty()) {
            if (!"/api/readiness/series".equals(path)) {
                throw new SecurityException("Query parameters are forbidden on this gateway route");
            }
            Set<String> seen = new HashSet<>();
            for (String pair : rawQuery.split("&")) {
                if (pair.isEmpty()) throw new SecurityException("Gateway query is malformed");
                String[] parts = pair.split("=", 2);
                String key = URLDecoder.decode(parts[0], StandardCharsets.UTF_8);
                String value = parts.length == 2 ? URLDecoder.decode(parts[1], StandardCharsets.UTF_8) : "";
                if (!SERIES_QUERY_KEYS.contains(key) || !seen.add(key) || value.length() > 160) {
                    throw new SecurityException("Gateway query is invalid");
                }
            }
        }
        return rawPath;
    }

    private String readBounded(InputStream stream) throws Exception {
        if (stream == null) return "";
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int total = 0;
        int read;
        while ((read = stream.read(buffer)) != -1) {
            total += read;
            if (total > MAX_RESPONSE_BYTES) throw new SecurityException("Gateway response exceeds bounded size");
            output.write(buffer, 0, read);
        }
        return new String(output.toByteArray(), StandardCharsets.UTF_8);
    }

    private String callGateway(String requestJson) throws Exception {
        String relativePath = validateRelativePath(requestJson);
        URL base = gatewayBaseUrl();
        URL target = new URL(base, relativePath);
        int basePort = base.getPort() == -1 ? base.getDefaultPort() : base.getPort();
        int targetPort = target.getPort() == -1 ? target.getDefaultPort() : target.getPort();
        if (!base.getProtocol().equalsIgnoreCase(target.getProtocol())
                || !base.getHost().equalsIgnoreCase(target.getHost())
                || basePort != targetPort) {
            throw new SecurityException("Gateway origin escape rejected");
        }

        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod("GET");
        connection.setRequestProperty("Accept", "application/json");
        String packed = getPreferences(MODE_PRIVATE).getString("gateway_token", "");
        String token = decrypt(packed);
        if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);

        int contentLength = connection.getContentLength();
        if (contentLength > MAX_RESPONSE_BYTES) throw new SecurityException("Gateway response exceeds bounded size");
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        String text = readBounded(stream);
        if (code < 200 || code >= 300) throw new IllegalStateException("NEXUS gateway HTTP " + code);
        JSONObject payload = new JSONObject(text);
        if (!"nexus.dashboard.read.v1".equals(payload.optString("contract_version"))) {
            throw new SecurityException("Incompatible NEXUS gateway response");
        }
        return payload.toString();
    }

    private String callPublicMarket(String symbol, String interval) throws Exception {
        String normalizedSymbol = symbol == null ? "" : symbol.trim().toUpperCase();
        if (!normalizedSymbol.matches("[A-Z0-9]{3,32}")) {
            throw new SecurityException("Unsupported public market symbol");
        }
        if (!PUBLIC_INTERVALS.contains(interval)) {
            throw new SecurityException("Unsupported public market interval");
        }
        String query = "category=spot&symbol="
                + URLEncoder.encode(normalizedSymbol, StandardCharsets.UTF_8)
                + "&interval=" + URLEncoder.encode(interval, StandardCharsets.UTF_8)
                + "&limit=120";
        URL target = new URL(BYBIT_BASE_URL + "/v5/market/kline?" + query);
        if (!"https".equalsIgnoreCase(target.getProtocol()) || !"api.bybit.com".equalsIgnoreCase(target.getHost())) {
            throw new SecurityException("Public market origin rejected");
        }

        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod("GET");
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("User-Agent", "nexus-mobile/1.0");
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        String text = readBounded(stream);
        if (code < 200 || code >= 300) throw new IllegalStateException("Bybit public market HTTP " + code);
        JSONObject payload = new JSONObject(text);
        if (payload.optInt("retCode", -1) != 0) {
            throw new IllegalStateException("Bybit public market rejected request");
        }
        return payload.toString();
    }

    public final class NativeGateway {
        @JavascriptInterface public boolean isAvailable() { return true; }

        @JavascriptInterface public String gatewayInfo() {
            try {
                URL base = gatewayBaseUrl();
                return new JSONObject()
                        .put("mode", "secure-gateway")
                        .put("origin", base.getProtocol() + "://" + base.getAuthority())
                        .put("readOnly", true)
                        .toString();
            } catch (Exception e) {
                return "{\"mode\":\"blocked\",\"readOnly\":true}";
            }
        }

        @JavascriptInterface public void saveKey(String id, String value) {
            assertGatewaySecretId(id);
            try {
                String encrypted = value == null || value.isEmpty() ? "" : encrypt(value);
                getPreferences(MODE_PRIVATE).edit().putString("gateway_token", encrypted).apply();
            } catch (Exception e) { throw new IllegalStateException(e); }
        }

        @JavascriptInterface public boolean hasKey(String id) {
            try {
                assertGatewaySecretId(id);
                return !getPreferences(MODE_PRIVATE).getString("gateway_token", "").isEmpty();
            } catch (Exception e) {
                return false;
            }
        }

        @JavascriptInterface public void deleteKey(String id) {
            assertGatewaySecretId(id);
            getPreferences(MODE_PRIVATE).edit().remove("gateway_token").apply();
        }

        @JavascriptInterface public void request(String requestId, String requestJson) {
            executor.execute(() -> {
                boolean ok = true;
                String payload;
                try { payload = callGateway(requestJson); }
                catch (Exception e) { ok = false; payload = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage(); }
                final String script = "window.NexusNativeResult(" + JSONObject.quote(requestId) + "," + ok + "," + JSONObject.quote(payload) + ")";
                runOnUiThread(() -> webView.evaluateJavascript(script, null));
            });
        }

        @JavascriptInterface public void requestPublicMarket(String requestId, String symbol, String interval) {
            executor.execute(() -> {
                boolean ok = true;
                String payload;
                try { payload = callPublicMarket(symbol, interval); }
                catch (Exception e) { ok = false; payload = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage(); }
                final String script = "window.NexusPublicMarketResult(" + JSONObject.quote(requestId) + "," + ok + "," + JSONObject.quote(payload) + ")";
                runOnUiThread(() -> webView.evaluateJavascript(script, null));
            });
        }
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        executor.shutdownNow();
        if (webView != null) { webView.removeJavascriptInterface("NexusNative"); webView.destroy(); webView = null; }
        super.onDestroy();
    }
}
