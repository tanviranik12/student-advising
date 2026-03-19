package com.university.adminportal.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/scheduling")
public class SchedulingController {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${ai.service.base-url:http://localhost:8000}")
    private String aiBaseUrl;

    @GetMapping("/reminders")
    public ResponseEntity<Map<String, Object>> getReminders() {
        Map<String, Object> body = new HashMap<>();
        body.put("category", "Scheduling & Notices");
        body.put("upcoming", List.of(
                "Registration deadline: " + LocalDate.now().plusDays(7),
                "Midterm exams start: " + LocalDate.now().plusDays(30),
                "Project submission deadline: " + LocalDate.now().plusDays(45)
        ));
        return ResponseEntity.ok(body);
    }

    @PostMapping("/suggest")
    public ResponseEntity<Map<String, Object>> suggestSchedule(@RequestBody Map<String, Object> payload) {
        Map<String, Object> aiResponse = restTemplate.postForObject(
                aiBaseUrl + "/ai/schedule-suggest", payload, Map.class);
        return ResponseEntity.ok(aiResponse);
    }
}

