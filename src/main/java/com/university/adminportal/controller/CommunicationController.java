package com.university.adminportal.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/communication")
public class CommunicationController {

    @GetMapping("/channels")
    public ResponseEntity<Map<String, Object>> getChannels() {
        Map<String, Object> body = new HashMap<>();
        body.put("category", "Internal Communication");
        body.put("channels", List.of(
                "Faculty announcements",
                "Student notices",
                "Administrative memos",
                "Meeting agendas and minutes"
        ));
        return ResponseEntity.ok(body);
    }

    @PostMapping("/draft")
    public ResponseEntity<Map<String, Object>> draftMessage(@RequestBody Map<String, Object> payload) {
        String audience = (String) payload.getOrDefault("audience", "students");
        String topic = (String) payload.getOrDefault("topic", "general update");

        Map<String, Object> response = new HashMap<>();
        response.put("audience", audience);
        response.put("topic", topic);
        response.put("draft", "Dear " + audience + ",\n\nThis is an automated draft regarding: " + topic + ". Please review and customize before sending.\n");
        return ResponseEntity.ok(response);
    }
}

