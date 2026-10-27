class Solution {
    static class Node {
        int val;
        Node prev, next;
        Node(int val) { this.val = val; }
    }

    public int build(int[] values) {
        Node head = null, tail = null;
        Set<Integer> seen = new HashSet<>();
        for (int v : values) {
            if (!seen.add(v)) continue;
            Node node = new Node(v);
            if (head == null) {
                head = node;
            } else {
                tail.next = node;
                node.prev = tail;
            }
            tail = node;
        }
        return seen.size();
    }
}
