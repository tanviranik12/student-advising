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
@RequestMapping("/api/advising")
public class StudentAdvisingController {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${ai.service.base-url:http://localhost:8000}")
    private String aiBaseUrl;

    @GetMapping("/faqs")
    public ResponseEntity<Map<String, Object>> getFaqs() {
        Map<String, Object> body = new HashMap<>();
        body.put("category", "Student Queries & Advising");
        body.put("faqs", List.of(
                "How do I select courses and check prerequisites?",
                "What are the rules for course add/drop and retake?",
                "How do I know if I’m at risk of academic probation?",
                "What are the guidelines for internship, capstone, and projects?"
        ));
        return ResponseEntity.ok(body);
    }

    @PostMapping("/plan")
    public ResponseEntity<Map<String, Object>> getAcademicPlan(@RequestBody Map<String, Object> payload) {
        Map<String, Object> body = new HashMap<>(payload);
        Map<String, Object> aiResponse = restTemplate.postForObject(
                aiBaseUrl + "/ai/advise", body, Map.class);
        return ResponseEntity.ok(aiResponse);
    }
}

