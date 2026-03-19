package com.university.adminportal.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/documentation")
public class DocumentationController {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${ai.service.base-url:http://localhost:8000}")
    private String aiBaseUrl;

    @GetMapping("/types")
    public ResponseEntity<Map<String, Object>> getDocumentTypes() {
        Map<String, Object> body = new HashMap<>();
        body.put("category", "Academic Documentation");
        body.put("forms", List.of(
                "Course registration form",
                "Course withdrawal form",
                "Credit transfer / exemption request",
                "Internship approval form",
                "Capstone project approval form"
        ));
        body.put("certificates", List.of(
                "Bonafide certificate",
                "No Objection Certificate (NOC)",
                "Recommendation letter",
                "Custom academic letter"
        ));
        return ResponseEntity.ok(body);
    }

    @PostMapping("/generate")
    public ResponseEntity<Map<String, Object>> generateDocument(@RequestBody Map<String, Object> payload) {
        Map<String, Object> aiResponse = restTemplate.postForObject(
                aiBaseUrl + "/ai/document-draft", payload, Map.class);
        return ResponseEntity.ok(aiResponse);
    }
}

