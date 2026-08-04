package com.saladinayoubi.lbankmobile;

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

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public final class MainActivity extends Activity {
    private static final String KEY_ALIAS = "nexus_provider_keys";
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
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
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

    private String readAll(InputStream stream) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
        StringBuilder out = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) out.append(line).append('\n');
        return out.toString().trim();
    }

    private JSONObject postJson(String url, JSONObject body, JSONObject headers) throws Exception {
        URL parsed = new URL(url);
        String protocol = parsed.getProtocol();
        if (!"https".equals(protocol) && !("http".equals(protocol) && ("127.0.0.1".equals(parsed.getHost()) || "localhost".equals(parsed.getHost()) || parsed.getHost().startsWith("192.168.") || parsed.getHost().startsWith("10.")))) {
            throw new SecurityException("Only HTTPS or local-network HTTP endpoints are allowed");
        }
        HttpURLConnection connection = (HttpURLConnection) parsed.openConnection();
        connection.setConnectTimeout(20000);
        connection.setReadTimeout(90000);
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json");
        JSONArray names = headers.names();
        if (names != null) for (int i = 0; i < names.length(); i++) {
            String name = names.getString(i);
            connection.setRequestProperty(name, headers.getString(name));
        }
        try (OutputStream os = connection.getOutputStream()) {
            os.write(body.toString().getBytes(StandardCharsets.UTF_8));
        }
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        String text = stream == null ? "" : readAll(stream);
        if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code + ": " + text);
        return new JSONObject(text);
    }

    private String callProvider(JSONObject request) throws Exception {
        JSONObject p = request.getJSONObject("provider");
        JSONArray messages = request.getJSONArray("messages");
        String type = p.getString("type");
        String base = p.getString("baseUrl").replaceAll("/$", "");
        String model = p.getString("model");
        String key = decrypt(getPreferences(MODE_PRIVATE).getString("key_" + p.getString("id"), ""));
        if (!"ollama".equals(type) && key.isEmpty()) throw new IllegalStateException("API Key تنظیم نشده");
        JSONObject headers = new JSONObject();
        JSONObject body = new JSONObject();
        JSONObject response;

        if ("openai-compatible".equals(type)) {
            headers.put("Authorization", "Bearer " + key);
            body.put("model", model).put("messages", messages).put("temperature", 0.25);
            response = postJson(base + "/chat/completions", body, headers);
            return response.getJSONArray("choices").getJSONObject(0).getJSONObject("message").optString("content");
        }
        if ("anthropic".equals(type)) {
            headers.put("x-api-key", key).put("anthropic-version", "2023-06-01");
            JSONArray filtered = new JSONArray();
            String system = "";
            for (int i = 0; i < messages.length(); i++) {
                JSONObject m = messages.getJSONObject(i);
                if ("system".equals(m.getString("role"))) system = m.getString("content"); else filtered.put(m);
            }
            body.put("model", model).put("max_tokens", 1800).put("messages", filtered).put("system", system);
            response = postJson(base + "/v1/messages", body, headers);
            JSONArray content = response.getJSONArray("content");
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < content.length(); i++) out.append(content.getJSONObject(i).optString("text"));
            return out.toString();
        }
        if ("gemini".equals(type)) {
            StringBuilder prompt = new StringBuilder();
            for (int i = 0; i < messages.length(); i++) {
                JSONObject m = messages.getJSONObject(i);
                prompt.append(m.getString("role")).append(": ").append(m.getString("content")).append("\n\n");
            }
            body.put("contents", new JSONArray().put(new JSONObject().put("parts", new JSONArray().put(new JSONObject().put("text", prompt.toString())))));
            response = postJson(base + "/v1beta/models/" + model + ":generateContent?key=" + java.net.URLEncoder.encode(key, "UTF-8"), body, headers);
            return response.getJSONArray("candidates").getJSONObject(0).getJSONObject("content").getJSONArray("parts").getJSONObject(0).optString("text");
        }
        if ("ollama".equals(type)) {
            body.put("model", model).put("stream", false).put("messages", messages);
            response = postJson(base + "/api/chat", body, headers);
            return response.getJSONObject("message").optString("content");
        }
        throw new IllegalArgumentException("نوع سرویس پشتیبانی نمی‌شود");
    }

    public final class NativeGateway {
        @JavascriptInterface public boolean isAvailable() { return true; }

        @JavascriptInterface public void saveKey(String providerId, String value) {
            try {
                String encrypted = value == null || value.isEmpty() ? "" : encrypt(value);
                getPreferences(MODE_PRIVATE).edit().putString("key_" + providerId, encrypted).apply();
            } catch (Exception e) { throw new IllegalStateException(e); }
        }

        @JavascriptInterface public boolean hasKey(String providerId) {
            return !getPreferences(MODE_PRIVATE).getString("key_" + providerId, "").isEmpty();
        }

        @JavascriptInterface public void deleteKey(String providerId) {
            getPreferences(MODE_PRIVATE).edit().remove("key_" + providerId).apply();
        }

        @JavascriptInterface public void request(String requestId, String requestJson) {
            executor.execute(() -> {
                boolean ok = true;
                String payload;
                try { payload = callProvider(new JSONObject(requestJson)); }
                catch (Exception e) { ok = false; payload = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage(); }
                final String script = "window.NexusNativeResult(" + JSONObject.quote(requestId) + "," + ok + "," + JSONObject.quote(payload) + ")";
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
