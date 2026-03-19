package com.university.adminportal.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/admin-systems")
public class AdminSystemsController {

    @GetMapping("/overview")
    public ResponseEntity<Map<String, Object>> getOverview() {
        Map<String, Object> body = new HashMap<>();
        body.put("category", "Administrative Systems");
        body.put("capabilities", List.of(
                "Track service performance and turnaround times",
                "Generate administrative reports and dashboards",
                "Support audits, inspections, and compliance reporting"
        ));
        return ResponseEntity.ok(body);
    }
}

