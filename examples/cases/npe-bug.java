class Solution {
    public ListNode reverseList(ListNode head) {
        ListNode prev = null;
        ListNode curr = head;
        while (curr != null) {
            curr.next = prev;
            prev = curr;
            curr = curr.next.next;
        }
        return prev;
    }
}
