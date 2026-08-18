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
import java.io.OutputStream;
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
    private static final int MAX_REQUEST_CHARS = 16_384;
    private static final String BYBIT_BASE_URL = "https://api.bybit.com";

    private static final Set<String> PUBLIC_INTERVALS = new HashSet<>(Arrays.asList("15", "60", "240"));
    private static final Set<String> DASHBOARD_PATHS = new HashSet<>(Arrays.asList(
            "/health", "/api/readiness/summary", "/api/readiness/series",
            "/api/mission-control", "/api/integrations/zotero", "/api/integrations/research"
    ));
    private static final Set<String> PRODUCT_GET_PATHS = new HashSet<>(Arrays.asList(
            "/api/product/overview", "/api/product/paper", "/api/product/paper/events",
            "/api/product/strategies", "/api/product/mission-control", "/api/product/mission/full", "/api/product/live",
            "/api/product/data/registry", "/api/product/research/last", "/api/product/risk",
            "/api/product/recovery", "/api/product/notifications"
    ));
    private static final Set<String> PRODUCT_POST_PATHS = new HashSet<>(Arrays.asList(
            "/api/product/paper/order", "/api/product/paper/auto", "/api/product/research/run",
            "/api/product/session", "/api/product/kill-switch"
    ));
    private static final Set<String> SERIES_QUERY_KEYS = new HashSet<>(Arrays.asList("symbol", "timeframe", "limit", "offset"));
    private static final Set<String> AI_REQUEST_KEYS = new HashSet<>(Arrays.asList("session_id", "conversation_id", "turn_id", "message"));
    private static final Set<String> PAPER_ORDER_KEYS = new HashSet<>(Arrays.asList("operation", "symbol", "timeframe", "side", "quantity", "reference_price", "stop_price", "target_price"));
    private static final Set<String> RESEARCH_KEYS = new HashSet<>(Arrays.asList("symbol", "timeframe", "family", "limit"));

    private WebView webView;
    private final ExecutorService executor = Executors.newFixedThreadPool(4);

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override protected void onCreate(Bundle savedInstanceState) {
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
        webView.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                if ("file:///android_asset/index.html".equals(url)) {
                    view.evaluateJavascript("(function(){var s=document.createElement('script');s.src='mobile-canonical-client.js';document.body.appendChild(s)})()", null);
                }
            }
        });
        webView.setWebChromeClient(new WebChromeClient());
        webView.loadUrl("file:///android_asset/index.html");
    }

    private SecretKey getOrCreateKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY_ALIAS)) return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null)).getSecretKey();
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return generator.generateKey();
    }

    private String encrypt(String plain) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        return Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + "." + Base64.encodeToString(cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
    }

    private String decrypt(String packed) throws Exception {
        if (packed == null || !packed.contains(".")) return "";
        String[] parts = packed.split("\\.", 2);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    private void assertGatewaySecretId(String id) {
        if (!GATEWAY_SECRET_ID.equals(id)) throw new SecurityException("Only the NEXUS gateway token is accepted by the native bridge");
    }

    private URL gatewayBaseUrl() throws Exception {
        URL base = new URL(BuildConfig.NEXUS_GATEWAY_URL);
        if (!"https".equalsIgnoreCase(base.getProtocol())) throw new SecurityException("Android NEXUS gateway must use HTTPS");
        if (base.getUserInfo() != null || base.getQuery() != null || base.getRef() != null || !(base.getPath().isEmpty() || "/".equals(base.getPath()))) {
            throw new SecurityException("Android NEXUS gateway configuration must be an HTTPS origin only");
        }
        return base;
    }

    private URL gatewayTarget(String relativePath) throws Exception {
        URL base = gatewayBaseUrl();
        URL target = new URL(base, relativePath);
        int basePort = base.getPort() == -1 ? base.getDefaultPort() : base.getPort();
        int targetPort = target.getPort() == -1 ? target.getDefaultPort() : target.getPort();
        if (!base.getProtocol().equalsIgnoreCase(target.getProtocol()) || !base.getHost().equalsIgnoreCase(target.getHost()) || basePort != targetPort) {
            throw new SecurityException("Gateway origin escape rejected");
        }
        return target;
    }

    private String gatewayToken() throws Exception {
        return decrypt(getPreferences(MODE_PRIVATE).getString("gateway_token", ""));
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

    private HttpsURLConnection connection(URL target, String method) throws Exception {
        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json");
        String token = gatewayToken();
        if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);
        return connection;
    }

    private String checkedJson(HttpsURLConnection connection, boolean requireDashboardContract) throws Exception {
        int contentLength = connection.getContentLength();
        if (contentLength > MAX_RESPONSE_BYTES) throw new SecurityException("Gateway response exceeds bounded size");
        int code = connection.getResponseCode();
        String text = readBounded(code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream());
        if (code < 200 || code >= 300) throw new IllegalStateException("NEXUS gateway HTTP " + code);
        JSONObject payload = new JSONObject(text);
        String contract = payload.optString("contract_version", "");
        if (requireDashboardContract && !"nexus.dashboard.read.v1".equals(contract)) throw new SecurityException("Incompatible NEXUS dashboard response");
        if (!requireDashboardContract && !contract.startsWith("nexus.")) throw new SecurityException("Incompatible NEXUS product response");
        if (payload.optBoolean("live_trading_authority", false)) throw new SecurityException("Remote product attempted to widen Live authority");
        return payload.toString();
    }

    private String validateDashboardPath(String requestJson) throws Exception {
        if (requestJson == null || requestJson.length() > 4096) throw new SecurityException("Gateway request is malformed or oversized");
        JSONObject request = new JSONObject(requestJson);
        Iterator<String> keys = request.keys();
        if (!keys.hasNext()) throw new SecurityException("Gateway request is empty");
        String only = keys.next();
        if (!"path".equals(only) || keys.hasNext()) throw new SecurityException("Only a bounded gateway path is accepted");
        String raw = request.getString("path");
        URI relative = new URI(raw);
        if (raw.length() > 4096 || raw.contains("#") || raw.startsWith("//") || relative.isAbsolute() || relative.getHost() != null || relative.getUserInfo() != null) {
            throw new SecurityException("Gateway path is invalid");
        }
        String path = relative.getPath();
        if (!DASHBOARD_PATHS.contains(path)) throw new SecurityException("Gateway route is not allowlisted");
        String query = relative.getRawQuery();
        if (query != null && !query.isEmpty()) {
            if (!"/api/readiness/series".equals(path)) throw new SecurityException("Query parameters are forbidden on this gateway route");
            Set<String> seen = new HashSet<>();
            for (String pair : query.split("&")) {
                String[] parts = pair.split("=", 2);
                String key = URLDecoder.decode(parts[0], StandardCharsets.UTF_8);
                String value = parts.length == 2 ? URLDecoder.decode(parts[1], StandardCharsets.UTF_8) : "";
                if (!SERIES_QUERY_KEYS.contains(key) || !seen.add(key) || value.length() > 160) throw new SecurityException("Gateway query is invalid");
            }
        }
        return raw;
    }

    private String validateProductPath(String method, String raw) throws Exception {
        if (!("GET".equals(method) || "POST".equals(method))) throw new SecurityException("Unsupported product method");
        if (raw == null || raw.length() > 1024 || raw.contains("#") || raw.startsWith("//")) throw new SecurityException("Product path is invalid");
        URI relative = new URI(raw);
        if (relative.isAbsolute() || relative.getHost() != null || relative.getUserInfo() != null) throw new SecurityException("Absolute product URLs are forbidden");
        String path = relative.getPath();
        if ("GET".equals(method) && !PRODUCT_GET_PATHS.contains(path)) throw new SecurityException("Product GET route is not allowlisted");
        if ("POST".equals(method) && !PRODUCT_POST_PATHS.contains(path)) throw new SecurityException("Product POST route is not allowlisted");
        String query = relative.getRawQuery();
        if (query != null && !query.isEmpty()) {
            if (!("GET".equals(method) && ("/api/product/paper/events".equals(path) || "/api/product/notifications".equals(path)))) {
                throw new SecurityException("Query parameters are forbidden on this product route");
            }
            String[] pairs = query.split("&");
            if (pairs.length != 1) throw new SecurityException("Product query is invalid");
            String[] parts = pairs[0].split("=", 2);
            String key = URLDecoder.decode(parts[0], StandardCharsets.UTF_8);
            String value = parts.length == 2 ? URLDecoder.decode(parts[1], StandardCharsets.UTF_8) : "";
            if (!"limit".equals(key) || !value.matches("[0-9]{1,4}")) throw new SecurityException("Product limit query is invalid");
        }
        return raw;
    }

    private JSONObject validateProductBody(String path, String bodyJson) throws Exception {
        if (bodyJson == null || bodyJson.length() < 2 || bodyJson.length() > MAX_REQUEST_CHARS) throw new SecurityException("Product body is malformed or oversized");
        JSONObject payload = new JSONObject(bodyJson);
        Set<String> keys = new HashSet<>();
        Iterator<String> iterator = payload.keys();
        while (iterator.hasNext()) keys.add(iterator.next());
        if ("/api/product/paper/auto".equals(path)) {
            if (!keys.isEmpty()) throw new SecurityException("Auto Paper body must be empty");
        } else if ("/api/product/paper/order".equals(path)) {
            if (!keys.equals(PAPER_ORDER_KEYS)) throw new SecurityException("Paper order schema mismatch");
            for (String key : PAPER_ORDER_KEYS) if (payload.optString(key, "").length() > 160) throw new SecurityException("Paper field out of bounds");
        } else if ("/api/product/research/run".equals(path)) {
            if (!keys.equals(RESEARCH_KEYS)) throw new SecurityException("Research schema mismatch");
            if (!(payload.opt("limit") instanceof Integer)) throw new SecurityException("Research limit must be integer");
        } else if ("/api/product/session".equals(path)) {
            if (!(keys.size() == 1 && keys.contains("open") && payload.opt("open") instanceof Boolean)) throw new SecurityException("Session schema mismatch");
        } else if ("/api/product/kill-switch".equals(path)) {
            if (!(keys.size() == 2 && keys.contains("enabled") && keys.contains("reason_code") && payload.opt("enabled") instanceof Boolean)) throw new SecurityException("Kill-switch schema mismatch");
            String reason = payload.optString("reason_code", "");
            if (reason.isEmpty() || reason.length() > 100) throw new SecurityException("Kill-switch reason out of bounds");
        }
        return payload;
    }

    private String callDashboard(String requestJson) throws Exception {
        String path = validateDashboardPath(requestJson);
        return checkedJson(connection(gatewayTarget(path), "GET"), true);
    }

    private String callAiRoom(String requestJson) throws Exception {
        if (requestJson == null || requestJson.length() < 2 || requestJson.length() > MAX_REQUEST_CHARS) throw new SecurityException("AI Room request is malformed or oversized");
        JSONObject payload = new JSONObject(requestJson);
        Set<String> keys = new HashSet<>();
        Iterator<String> iterator = payload.keys();
        while (iterator.hasNext()) keys.add(iterator.next());
        if (!keys.equals(AI_REQUEST_KEYS)) throw new SecurityException("AI Room request schema mismatch");
        for (String key : AI_REQUEST_KEYS) {
            String value = payload.getString(key);
            int limit = "message".equals(key) ? 8192 : 160;
            if (value.trim().isEmpty() || value.length() > limit) throw new SecurityException("AI Room field out of bounds: " + key);
        }
        HttpsURLConnection connection = connection(gatewayTarget("/api/ai-room/message"), "POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(body.length);
        try (OutputStream output = connection.getOutputStream()) { output.write(body); }
        return checkedJson(connection, true);
    }

    private String callProduct(String method, String rawPath, String bodyJson) throws Exception {
        String safePath = validateProductPath(method, rawPath);
        HttpsURLConnection connection = connection(gatewayTarget(safePath), method);
        if ("POST".equals(method)) {
            JSONObject payload = validateProductBody(new URI(safePath).getPath(), bodyJson);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(body); }
        }
        return checkedJson(connection, false);
    }

    private String callPublicMarket(String symbol, String interval) throws Exception {
        String safeSymbol = symbol == null ? "" : symbol.trim().toUpperCase();
        if (!safeSymbol.matches("[A-Z0-9]{3,32}")) throw new SecurityException("Unsupported public market symbol");
        if (!PUBLIC_INTERVALS.contains(interval)) throw new SecurityException("Unsupported public market interval");
        String query = "category=spot&symbol=" + URLEncoder.encode(safeSymbol, StandardCharsets.UTF_8) + "&interval=" + URLEncoder.encode(interval, StandardCharsets.UTF_8) + "&limit=120";
        URL target = new URL(BYBIT_BASE_URL + "/v5/market/kline?" + query);
        if (!"https".equalsIgnoreCase(target.getProtocol()) || !"api.bybit.com".equalsIgnoreCase(target.getHost())) throw new SecurityException("Public market origin rejected");
        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod("GET");
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("User-Agent", "nexus-mobile/3.2");
        int code = connection.getResponseCode();
        String text = readBounded(code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream());
        if (code < 200 || code >= 300) throw new IllegalStateException("Bybit public market HTTP " + code);
        JSONObject payload = new JSONObject(text);
        if (payload.optInt("retCode", -1) != 0) throw new IllegalStateException("Bybit public market rejected request");
        return payload.toString();
    }

    private void deliver(String callback, String id, boolean ok, String payload) {
        final String script = "window." + callback + "(" + JSONObject.quote(id) + "," + ok + "," + JSONObject.quote(payload) + ")";
        runOnUiThread(() -> webView.evaluateJavascript(script, null));
    }

    public final class NativeGateway {
        @JavascriptInterface public boolean isAvailable() { return true; }
        @JavascriptInterface public String gatewayInfo() {
            try {
                URL base = gatewayBaseUrl();
                return new JSONObject().put("mode", "secure-gateway").put("origin", base.getProtocol() + "://" + base.getAuthority())
                        .put("canonicalProduct", true).put("boundedAiRoom", true).put("localPaperFallback", true)
                        .put("liveTradingAuthority", false).toString();
            } catch (Exception e) {
                return "{\"mode\":\"blocked\",\"canonicalProduct\":false,\"localPaperFallback\":true,\"liveTradingAuthority\":false}";
            }
        }
        @JavascriptInterface public void saveKey(String id, String value) {
            assertGatewaySecretId(id);
            try { getPreferences(MODE_PRIVATE).edit().putString("gateway_token", value == null || value.isEmpty() ? "" : encrypt(value)).apply(); }
            catch (Exception e) { throw new IllegalStateException(e); }
        }
        @JavascriptInterface public boolean hasKey(String id) {
            try { assertGatewaySecretId(id); return !getPreferences(MODE_PRIVATE).getString("gateway_token", "").isEmpty(); }
            catch (Exception e) { return false; }
        }
        @JavascriptInterface public void deleteKey(String id) { assertGatewaySecretId(id); getPreferences(MODE_PRIVATE).edit().remove("gateway_token").apply(); }
        @JavascriptInterface public void request(String id, String json) { executor.execute(() -> { try { deliver("NexusNativeResult", id, true, callDashboard(json)); } catch (Exception e) { deliver("NexusNativeResult", id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()); } }); }
        @JavascriptInterface public void requestAiRoom(String id, String json) { executor.execute(() -> { try { deliver("NexusAiRoomResult", id, true, callAiRoom(json)); } catch (Exception e) { deliver("NexusAiRoomResult", id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()); } }); }
        @JavascriptInterface public void requestProduct(String id, String method, String path, String bodyJson) { executor.execute(() -> { try { deliver("NexusProductResult", id, true, callProduct(method == null ? "" : method.trim().toUpperCase(), path, bodyJson == null ? "{}" : bodyJson)); } catch (Exception e) { deliver("NexusProductResult", id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()); } }); }
        @JavascriptInterface public void requestPublicMarket(String id, String symbol, String interval) { executor.execute(() -> { try { deliver("NexusPublicMarketResult", id, true, callPublicMarket(symbol, interval)); } catch (Exception e) { deliver("NexusPublicMarketResult", id, false, e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage()); } }); }
    }

    @Override public void onBackPressed() { if (webView != null && webView.canGoBack()) webView.goBack(); else super.onBackPressed(); }
    @Override protected void onDestroy() { executor.shutdownNow(); if (webView != null) { webView.removeJavascriptInterface("NexusNative"); webView.destroy(); webView = null; } super.onDestroy(); }
}
